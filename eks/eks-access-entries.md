# EKS access entries

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#IAM` `#RBAC`

Access entries decide which IAM principal may call the Kubernetes API, and as what. They are not Pod Identity and they are not IRSA. Those give a pod an AWS identity. This gives a human, a CI role, or a node role a Kubernetes identity. Mixing them up produces a 401 you will debug in the wrong console.

The old mechanism is the `aws-auth` ConfigMap in `kube-system`. It still works while the cluster authentication mode includes `CONFIG_MAP`. It is one object, edited in place, that maps both your admin role and the node role. A bad edit locks out `kubectl` and stops nodes joining. I do not want cluster access stored there on anything new.

---

## Authentication mode

| Mode | What the authenticator reads |
|---|---|
| `CONFIG_MAP` | Only `aws-auth`. Clusters old enough to still be here. |
| `API_AND_CONFIG_MAP` | Access entries and `aws-auth`. The migration mode. |
| `API` | Access entries only. `aws-auth` is ignored. |

You can move `CONFIG_MAP` to `API_AND_CONFIG_MAP`, and from there to `API`. You can move `API` back to `API_AND_CONFIG_MAP`. You cannot return to `CONFIG_MAP` once you have left it. That is fine. There is no reason to go back.

```bash
aws eks update-cluster-config \
  --name app \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

Create the cluster in `API_AND_CONFIG_MAP` with `bootstrapClusterCreatorAdminPermissions` true, unless an access entry for a break-glass role already exists in the same apply. `false` plus mode `API` is a control plane with no admin. The recovery is AWS support or a principal you forgot you added. See the [control plane note](./eks-control-plane-what-you-own.md).

---

## An entry and a policy are two calls

`create-access-entry` registers the principal. `associate-access-policy` says what that principal can do. An entry with no policy can authenticate and then fail every RBAC check. The authenticator log shows success. `kubectl auth can-i` shows no.

```bash
aws eks create-access-entry \
  --cluster-name app \
  --principal-arn arn:aws:iam::111122223333:role/PlatformBreakGlass \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name app \
  --principal-arn arn:aws:iam::111122223333:role/PlatformBreakGlass \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
```

The policy ARN has no region and no account. Copy it. A hand-built ARN with the account ID in it does not match.

| Policy | Kubernetes equivalent | Who gets it |
|---|---|---|
| `AmazonEKSClusterAdminPolicy` | `cluster-admin` | One break-glass role. Maybe the platform on-call role, cluster scoped. |
| `AmazonEKSAdminPolicy` | `admin` | A team that administers its namespaces, not the cluster. |
| `AmazonEKSEditPolicy` | `edit` | Developers and CI, namespace scoped. |
| `AmazonEKSViewPolicy` | `view` | Read-only. |

Namespace scope:

```bash
aws eks associate-access-policy \
  --cluster-name app \
  --principal-arn arn:aws:iam::111122223333:role/PaymentsDeploy \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy \
  --access-scope type=namespace,namespaces=payments
```

CI gets `Edit` on the namespaces it deploys, not `ClusterAdmin`. Cluster admin in a pipeline is how a bad manifest edits `aws-auth`, ClusterRoles, and the CNI. `Edit` cannot do that.

These policies are the coarse grant. Finer rules are still Role and RoleBinding in the namespace. Access entries do not replace RBAC. They are the AWS-side binding that gets the principal into a Kubernetes group. If you need a custom ClusterRole, associate the principal in a way that lands in a group you bind yourself, or stay with a Kubernetes binding for that one case. I use the AWS policies until a team needs something they do not express.

---

## Node roles are entries too

A managed node group created while the cluster is in `API` or `API_AND_CONFIG_MAP` gets an access entry of type `EC2_LINUX` for its node role. Fargate gets `FARGATE_LINUX`. That entry is what allows kubelet to register the node. It is not `AmazonEKSClusterAdminPolicy`. Never associate cluster admin with a node role. A pod that reaches the node role would then be cluster admin.

Self-managed nodes, and node groups that existed before you switched the mode, need the entry yourself:

```bash
aws eks create-access-entry \
  --cluster-name app \
  --principal-arn arn:aws:iam::111122223333:role/EKSNodeRole \
  --type EC2_LINUX
```

Before you move the cluster to `API`, list entries and account for every role in `aws-auth`, including the node roles:

```bash
aws eks list-access-entries --cluster-name app
kubectl -n kube-system get configmap aws-auth -o yaml
```

Then change one human role to an access entry, assume it, and run `kubectl get ns` from that role with `aws-auth` still in place. Then do the node role. Then flip to `API`. Then, only after a node has joined and a drain has worked, delete the ConfigMap.

If you delete `aws-auth` while the mode still includes `CONFIG_MAP`, and the access entries are incomplete, nodes that roll will not come back. The log you want is the authenticator log, not the workload log. Enable it before the migration, not during it. The [control plane note](./eks-control-plane-what-you-own.md) has the logging call.

---

## What the caller actually is

The principal in the entry is the IAM role, not the role session name, and not the human user who assumed the role, unless that user calls the API directly. CI that assumes `PaymentsDeploy` needs the entry on `PaymentsDeploy`. An entry on the CI user does nothing once the pipeline has assumed the role.

SSO roles have a path. The ARN in the entry must match the ARN EKS sees. `aws sts get-caller-identity` from the same shell you use for `kubectl` is the ARN to copy. Paths (`aws-reserved/sso.amazonaws.com/...`) are a common mismatch. The console will show you a role name that is not the full ARN.

```bash
aws sts get-caller-identity
kubectl auth whoami
kubectl auth can-i get pods -n payments
kubectl auth can-i delete nodes
```

`whoami` is the Kubernetes user after the authenticator has done its work. If `get-caller-identity` is the role you expect and `whoami` fails, the entry is missing or the mode does not read entries yet. If `whoami` succeeds and `can-i` is no, the policy or the RBAC binding is missing. Those are different fixes.

---

## Break-glass

One role, cluster admin, no one uses it daily, the trust policy is the platform group plus MFA or a permission set you can retrieve when the normal role is broken. Daily admin through cluster admin means you will never notice that `Edit` was enough, and you will not notice when a deploy role has more than `Edit`.

I keep that role out of application pipelines and out of the node instance profile. It exists so a bad access-entry change is recoverable without opening a support case.
