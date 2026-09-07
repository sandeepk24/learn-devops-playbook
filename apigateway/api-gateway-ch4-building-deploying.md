# AWS API Gateway for DevOps Engineers, Part 4: Building and Deploying

*Part 4 of a 7-part series. Parts 1–3 covered core concepts — fundamentals and the request lifecycle, endpoint types and resource design, and integration types. This chapter gets hands-on with boto3. Part 5 covers security and access control, Part 6 covers traffic management and custom domains, and Part 7 covers observability and troubleshooting.*

Part 1 gave you the vocabulary. This chapter is where you actually build something, using boto3, since that's the tool most DevOps engineers reach for when they need to script infrastructure rather than click through a console. In practice you'd manage this with Terraform or CDK for anything long-lived, but understanding the raw API calls makes the higher-level tools far less magical — every Terraform resource in the `aws_api_gateway_*` family is a thin wrapper over exactly the calls below.

---

## Creating the API and a Resource Tree

Every REST API starts with a root resource (`/`) that AWS creates for you automatically. Everything else you build hangs off it.

```python
import boto3

client = boto3.client("apigateway", region_name="us-east-1")

# Create the REST API
api = client.create_rest_api(
    name="orders-service",
    description="Order management API for the fulfillment team",
    endpointConfiguration={"types": ["REGIONAL"]},
)
api_id = api["id"]

# Every API starts with a root resource ("/") — fetch its ID
resources = client.get_resources(restApiId=api_id)
root_id = next(r["id"] for r in resources["items"] if r["path"] == "/")

# Create /orders
orders_resource = client.create_resource(
    restApiId=api_id,
    parentId=root_id,
    pathPart="orders",
)

# Create /orders/{orderId} as a child of /orders
order_by_id = client.create_resource(
    restApiId=api_id,
    parentId=orders_resource["id"],
    pathPart="{orderId}",
)
```

Notice the resource tree mirrors the URL path exactly — `{orderId}` in curly braces becomes a path parameter, which your integration reads via `event["pathParameters"]["orderId"]` in a Lambda proxy integration, or via `$input.params('orderId')` in a mapping template.

---

## Wiring Up a Lambda Proxy Integration

This is the part people get wrong most often — forgetting that a Lambda proxy integration needs `apigateway.amazonaws.com` permission to invoke the function, separate from any IAM role the Gateway itself has.

```python
lambda_client = boto3.client("lambda", region_name="us-east-1")
account_id = boto3.client("sts").get_caller_identity()["Account"]
region = "us-east-1"
function_arn = f"arn:aws:lambda:{region}:{account_id}:function:orders-handler"

# Register the method
client.put_method(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="GET",
    authorizationType="NONE",  # we'll fix this in Part 5
)

# Point it at the Lambda function
client.put_integration(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="GET",
    type="AWS_PROXY",
    integrationHttpMethod="POST",  # Lambda invocations are always POST under the hood
    uri=f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{function_arn}/invocations",
)

# Grant API Gateway permission to invoke the function
lambda_client.add_permission(
    FunctionName="orders-handler",
    StatementId="apigateway-orders-get",
    Action="lambda:InvokeFunction",
    Principal="apigateway.amazonaws.com",
    SourceArn=f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/GET/orders",
)
```

That `SourceArn` scopes the Lambda invocation to exactly this method on this API. It's tempting to loosen that during debugging ("just let anything invoke it, I'll fix it later"), and that's exactly the kind of thing that survives into production because nobody circles back. Keep it scoped from the start.

---

## Request Validation: Rejecting Garbage Before It Reaches Your Code

This is a REST API feature HTTP API doesn't have, and it's a real reason to choose REST when your endpoint takes untrusted input. Instead of writing `if "email" not in body: return 400` in every handler, you can define a JSON Schema model and let API Gateway reject malformed requests before they ever invoke your Lambda — saving an invocation, and keeping validation logic in one declarative place instead of scattered across handlers.

```python
model = client.create_model(
    restApiId=api_id,
    name="CreateOrderRequest",
    contentType="application/json",
    schema=json.dumps({
        "$schema": "http://json-schema.org/draft-04/schema#",
        "title": "CreateOrderRequest",
        "type": "object",
        "required": ["customerId", "items"],
        "properties": {
            "customerId": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "object"},
            },
        },
    }),
)

validator = client.create_request_validator(
    restApiId=api_id,
    name="validate-body",
    validateRequestBody=True,
    validateRequestParameters=False,
)

client.put_method(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="POST",
    authorizationType="NONE",
    requestValidatorId=validator["id"],
    requestModels={"application/json": "CreateOrderRequest"},
)
```

A request that fails this validation gets a `400 Bad Request` with a body describing what's wrong, generated entirely by API Gateway — your Lambda never even cold-starts for it. On a high-traffic public endpoint that gets probed constantly by bots and scanners, this alone can meaningfully cut your invocation count and cost.

---

## Mapping Templates: When You Need Transformation, Not Just Proxying

If you're using a non-proxy (custom) integration, you write Velocity Template Language (VTL) to reshape the request before it hits the backend, and the response before it reaches the client. This is the part of API Gateway that feels the most like a different era of AWS — VTL is not a language anyone enjoys writing — but it's genuinely powerful when you want to decouple your backend entirely from HTTP semantics.

A minimal request mapping template that reshapes an incoming JSON body into something a DynamoDB `PutItem` call expects:

```velocity
{
  "TableName": "Orders",
  "Item": {
    "orderId": { "S": "$context.requestId" },
    "customerId": { "S": "$input.path('$.customerId')" },
    "createdAt": { "S": "$context.requestTime" }
  }
}
```

Wiring that into an AWS service integration (calling DynamoDB directly, no Lambda involved):

```python
client.put_integration(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="POST",
    type="AWS",
    integrationHttpMethod="POST",
    uri=f"arn:aws:apigateway:{region}:dynamodb:action/PutItem",
    credentials=f"arn:aws:iam::{account_id}:role/apigateway-dynamodb-role",
    requestTemplates={"application/json": open("request_template.vtl").read()},
)

client.put_integration_response(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="POST",
    statusCode="201",
    responseTemplates={"application/json": '{"status": "created"}'},
)
```

That `credentials` parameter needs an IAM role that API Gateway assumes, with permissions scoped to exactly the DynamoDB actions you need — not a broad `dynamodb:*`. It's a separate trust relationship from the Lambda invocation permission model, and it's easy to over-grant here because the error messages when you under-grant are unhelpfully generic ("Internal server error" in the response, with the real reason buried in CloudWatch execution logs).

---

## Deploying to a Stage

None of the above is live until you deploy.

```python
client.create_deployment(
    restApiId=api_id,
    stageName="dev",
    description="Initial deployment of orders endpoints",
)

print(f"Invoke URL: https://{api_id}.execute-api.{region}.amazonaws.com/dev/orders")
```

Every `put_method` or `put_integration` call you make after this point requires another deployment before it's reflected on that stage. If you're scripting this repeatedly, it's worth writing a small helper that diffs your intended config against the currently deployed one and only redeploys when something actually changed — otherwise every CI run creates a new deployment even when nothing moved, and your deployment history becomes noise.

### Stage variables, briefly

Stage variables let a single API definition serve multiple environments by parameterizing the integration target — commonly, pointing each stage at a different Lambda alias:

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/variables/lambdaAlias", "value": "prod"},
    ],
)
```

Then your integration URI references `${stageVariables.lambdaAlias}` instead of a hardcoded alias name, and the same method/integration config serves `dev`, `staging`, and `prod` by pointing at different Lambda versions without duplicating a single resource.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Writing input validation as the first ten lines of every Lambda handler | Define a request model and validator for endpoints with untrusted input, and let API Gateway reject garbage before it costs you an invocation |
| Granting `dynamodb:*` to the integration role because the real permission set is annoying to figure out | Scope the role to exactly the actions the mapping template calls (`PutItem`, `GetItem`, etc.) |
| Redeploying on every CI run regardless of whether config changed | Diff intended config against deployed config and only create a new deployment when something actually moved |
| Hardcoding a Lambda alias in the integration URI per environment | Use stage variables so one API definition serves every stage |
| Loosening a Lambda's `SourceArn` permission "temporarily" while debugging | Keep it scoped to the specific API/stage/method from the start — temporary permissions have a way of becoming permanent |

---

## What's Next

Part 5 covers security and access control in depth — IAM auth, Cognito user pools, Lambda authorizers, resource policies, private APIs, API keys, and mutual TLS. The `authorizationType="NONE"` left in this chapter's examples gets fixed there.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
