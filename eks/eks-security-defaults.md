# Security defaults on a new EKS cluster

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#Security` `#IAM`

These are the settings I want in place before the first application namespace exists. They are defaults, not a review of every workload. A workload that needs hostPath or a wider IAM action should say so in its own manifest, as an exception, with a reason.

Identity for pods is [Pod Identity](./eks-pod-identity.md) or [IRSA](./irsa-explained-real-eks-workloads.md). Who may call the API is [access entries](./eks-access-entries.md). The endpoint, the KMS key, and audit logs are in the [control plane note](./eks-control-plane-what-you-own.md). This note is the rest of the baseline, and the order I turn it on.

---

## The node is not a role the pods should have

IMDSv2, tokens required, hop limit 1, on the launch template or the EC2NodeClass. Hop limit 2 is the default that lets a pod on the node call the instance metadata service and receive the node role's credentials. Hop limit 1 stops the pod. The kubelet, which is on the host network, can still reach IMDS.

After the VPC CNI is running with its own service account, remove `AmazonEKS_CNI_Policy` from the node role. What should remain is worker-node registration and ECR pull in this account. Application S3, DynamoDB, and Secrets Manager actions do not belong on the node role "temporarily." Temporarily is how they are still there two years later.

Cross-account image pulls are a repository policy on the other account's ECR, plus network path to `ecr.api` and `ecr.dkr`. A 403 on pull is IAM. A timeout on pull is NAT or the missing VPC endpoints from the control plane note. Neither is fixed by making the node role an administrator.

---

## Pod security admission

PSA is on in current EKS versions. You opt namespaces in with labels. You do not install a separate webhook for the baseline.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payments
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

`restricted` means the pod runs as non-root, cannot escalate, drops capabilities, and sets a seccomp profile. Stock images that run as root will be rejected at create time. That is the point. The workaround people reach for is labeling the namespace `privileged`. Do that for `kube-system`, where the CNI needs it, and nowhere else until you have a specific pod and a ticket.

Roll `audit` and `warn` first if the namespace already has workloads. Read the warnings. Then `enforce`. Flipping enforce on a Friday on a namespace you have not audited will block the next deploy, which is better than blocking a running pod, and will still page someone.

A pod that passes `restricted`:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  seccompProfile:
    type: RuntimeDefault
containers:
  - name: api
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

`runAsNonRoot: true` without a non-root user in the image still fails. The image has to have a user, or the manifest sets `runAsUser`. `privileged`, `hostNetwork`, `hostPID`, and `hostPath` do not belong in this manifest.

---

## Network policy after you know the flows

The VPC CNI can enforce Kubernetes `NetworkPolicy` when network policy is enabled on the add-on. That is in-cluster. Security groups are still the VPC boundary, and without security groups for pods they are per node. Both are real. They are not substitutes.

I do not apply a default-deny on day one of a cluster I do not know. I do apply it on an application namespace once the egress list is written down: DNS to CoreDNS in `kube-system`, the other pods in the namespace, and the AWS or database endpoints that namespace actually calls. A default-deny copied from a template, without the DNS egress, takes the namespace off the network and the symptom is timeouts, not a policy denial anyone is tailing.

One policy engine. The VPC CNI agent, or Calico, not both.

---

## Secrets

Envelope encryption with your KMS key, at cluster create, so etcd is not holding plaintext. Anyone who can `get` the Secret in the API still receives the value. Encryption at rest is not RBAC.

Do not grant `edit` on a namespace and also store the database password in a Kubernetes Secret if the people with `edit` should not have the password. `edit` can read Secrets. If the password should live in AWS, the pod should read Secrets Manager or SSM with its own role, and the Kubernetes Secret should not exist. The Secrets Store CSI driver is the version of that which mounts a file. Use it when the process cannot call AWS and can only read a path. It is another DaemonSet and another IAM role. It is justified when the application is a file reader. It is overhead when the application already uses the AWS SDK.

Do not put production credentials in a ConfigMap. ConfigMaps are not even pretending to be secret, and they show up in `kubectl describe`.

---

## Images

Deploy by digest, or by an immutable tag your pipeline overwrites only by publishing a new tag. `:latest` in a Deployment means a rollback is "whatever the registry thinks latest is now," which may be the broken image. ECR scan on push is cheap. A critical finding does not, by itself, mean you block the deploy. It means someone looks at it before the next release, and the image is still the one you scanned, which brings you back to not using `:latest`.

---

## GuardDuty

If the account already has GuardDuty, turn on EKS Protection so audit logs are analyzed, and Runtime Monitoring if you want process-level findings from the nodes. If the account does not have GuardDuty, turning it on is an organization decision about findings volume and who is on the hook for them. I do not enable runtime monitoring in a cluster and then send the findings nowhere.

Audit logs have to be enabled for the audit-log detector to see anything. The control plane note turns on `audit` and `authenticator`. Runtime monitoring is an agent. Read what it runs as before you combine it with `restricted` on `kube-system`. It does not belong in application namespaces as a privileged sidecar you added by hand.

---

## What I do not do

I do not put the cluster API on `0.0.0.0/0` because CI was annoying to move.

I do not attach `AdministratorAccess` to the node role, the CNI role, or a pipeline role to see if that fixes the 403. It does. It also ends the investigation.

I do not share one Pod Identity role across every service in a namespace. The blast radius of a bug in one Deployment is then every AWS action that namespace can perform. One role per service account costs a few extra associations and is the whole point of not using the node role.

I do not disable PSA, or network policy, to get a vendor Helm chart green, and then leave it disabled. Label a dedicated namespace, or set the chart's security context. The chart is a guest.
