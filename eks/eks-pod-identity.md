# EKS Pod Identity

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#IAM` `#IRSA`

Pod Identity gives a pod an IAM role. The Kubernetes side is a service account. The AWS side is an association on the cluster: this namespace, this service account, this role. There is no OIDC provider and no trust policy that has to spell `system:serviceaccount:namespace:name` correctly. That string is where most IRSA outages live. The [IRSA note](./irsa-explained-real-eks-workloads.md) still applies if you are already on IRSA. Read it for least-privilege policies. This note is the other mechanism, and when I pick it.

Access entries are not this. Access entries let a role call the Kubernetes API. See [access entries](./eks-access-entries.md).

---

## What has to be running

The `eks-pod-identity-agent` add-on, as a DaemonSet, on every Linux EC2 node that will run these pods. There is no agent on Fargate, and the agent does not run on Windows nodes. Those pods stay on IRSA. A pod with an association, scheduled onto a node where the agent is missing, does not fall back to the IRSA annotation. The webhook has already chosen Pod Identity. Fix the agent before you debug the trust policy.

```bash
aws eks create-addon \
  --cluster-name app \
  --addon-name eks-pod-identity-agent \
  --resolve-conflicts OVERWRITE
```

The agent's job is to intercept the AWS credential call from the pod and exchange it with EKS. The pod does not mount a projected service account token for this. If you are looking for `AWS_WEB_IDENTITY_TOKEN_FILE` to prove Pod Identity is on, you are checking for IRSA. Pod Identity still ends at `aws sts get-caller-identity` showing the role. That is the check.

---

## The role and the association

Trust the Pod Identity service, and allow it to tag the session. Without `sts:TagSession` the association fails in a way that looks like a bad policy.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEksAuthToAssumeRoleForPodIdentity",
      "Effect": "Allow",
      "Principal": {
        "Service": "pods.eks.amazonaws.com"
      },
      "Action": [
        "sts:AssumeRole",
        "sts:TagSession"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestTag/kubernetes-namespace": "production",
          "aws:RequestTag/kubernetes-service-account": "api"
        }
      }
    }
  ]
}
```

The condition is optional and I keep it. The association is already scoped, and the condition means a second association cannot point some other service account at this role unless you also widen the trust. The request tags Pod Identity sets include `kubernetes-namespace`, `kubernetes-service-account`, `eks-cluster-name`, and `eks-cluster-arn`.

```bash
aws eks create-pod-identity-association \
  --cluster-name app \
  --namespace production \
  --service-account api \
  --role-arn arn:aws:iam::111122223333:role/api
```

The service account does not need `eks.amazonaws.com/role-arn`. That annotation is IRSA. Leave it off unless you meant IRSA.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api
  namespace: production
```

```yaml
spec:
  serviceAccountName: api
```

The namespace and the service account name in the association have to match the pod. They do not have to exist yet when you create the association. The pod does have to use that service account. The default service account is a different principal.

Permission policies on the role are the same least-privilege documents as IRSA. Pod Identity does not widen them. A Secrets Manager ARN without the `-*` suffix still fails. That class of mistake is in the IRSA note and it does not change here.

---

## If both are configured

If the service account has an IRSA annotation and a Pod Identity association, and the agent is running, Pod Identity is what the pod uses. You will debug the IRSA trust policy while the association is the thing that is wrong, or the reverse. Configure one. When you migrate, remove the annotation in the same change that adds the association, and read `get-caller-identity` before you call it done.

---

## Cross-account

IRSA can assume a role in another account directly, because the trust policy on that role names your cluster's OIDC provider. Pod Identity does it in two hops. The pod assumes a role in the cluster account. That role assumes a target role in the other account.

On the target role, trust the cluster-account role, require `sts:AssumeRole` and `sts:TagSession`, and constrain it with the Pod Identity request tags and `aws:PrincipalARN`. Current AWS docs use `aws:RequestTag/eks-cluster-arn`, `aws:RequestTag/kubernetes-namespace`, and `aws:RequestTag/kubernetes-service-account` for that condition. There was a period when the documented key was `aws:PrincipalTag`. If a target role was written against the old key, it still needs to match what the assume call sends. Check the role you have, not a screenshot from a year ago.

The agent also injects an `sts:ExternalId` of the form `region/account-id/cluster-name/namespace/service-account` on the cross-account assume. Use that as the condition if you are following the cross-account walkthrough that keys off ExternalId. Do not invent a second ExternalId in the application. The agent sets it.

Same-account associations do not need any of this. Most workloads are same-account.

---

## When I still use IRSA

The pod runs on Fargate or on a Windows node. Pod Identity has nowhere to put the agent. IRSA is the mechanism that works there.

The cluster already has a working OIDC provider and a pile of roles whose trust policies you do not want to touch this quarter. Migrating for its own sake is how you create an outage to delete a thumbprint.

A controller's documentation only shows the IRSA annotation and you do not have time to rewrite its install. The annotation works. Pod Identity can wait for that chart.

IRSA's failure mode, the one Pod Identity deletes, is the OIDC provider: wrong URL, a thumbprint that did not follow a certificate rotation, a `sub` condition with a typo in the namespace. `InvalidIdentityToken` in the workload is that class. Pod Identity moves the failure to "no association" or "agent not on the node," which is a shorter debug.

New cluster, I start with Pod Identity. I do not stand up an OIDC provider "just in case" and then run both.

---

## Checking it

```bash
aws eks list-pod-identity-associations --cluster-name app
kubectl -n kube-system get ds eks-pod-identity-agent
kubectl -n production exec deploy/api -- aws sts get-caller-identity
```

The identity should be `role/api`, not the node instance profile. Associations apply to pods created after the association exists. Restart the workload before you trust a negative result. If the identity is the node, the pod is not using the service account, the association namespace is wrong, or the agent is not on that node. If the call errors with access denied on `AssumeRole`, the trust policy principal or the tag condition does not match. If the identity is the role and the AWS API then returns `AccessDenied`, the identity works and the permission policy does not. Stop looking at the association.

A current AWS CLI in a debug pod can succeed while the application still has no credentials. Pod Identity is picked up by the container credential provider in the SDK. An image pinned to an old boto3 or an old AWS SDK never looks there. That is an image bump, not an IAM change.

`kubectl exec` needs a shell and the AWS CLI in the image. A distroless image will not give you that. A one-off pod with the same service account and `amazon/aws-cli` is the substitute. Delete it after. Do not leave a debug pod bound to a production role.
