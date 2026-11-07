# Deploying Keel to OpenShift

Keel runs as one container: FastAPI on port 8000 serves both the API and the built React app.
The image is built from `backend/Dockerfile` with the repo root as build context.

## 1. Project and AI key

```bash
oc new-project keel
# Optional. Without it Keel runs with no AI; measurements and verdicts do not use AI.
oc create secret generic keel-ai --from-literal=api_chatgpt=<your OpenAI key>
```

## 2. Build the image

From GitHub (the repository must be pushed, and reachable by the cluster):

```bash
oc new-build https://github.com/MuathOthman/meyerTurku.git --name=keel --strategy=docker
oc patch bc/keel -p '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"backend/Dockerfile"}}}}'
oc start-build keel --follow
```

For a private repository, add a source secret first (`oc create secret generic github
--from-literal=username=… --from-literal=password=<token> --type=kubernetes.io/basic-auth`) and
pass `--source-secret=github` to `oc new-build`.

## 3. Deploy

```bash
oc apply -f deploy/openshift.yaml
oc rollout status deploy/keel
oc get route keel -o jsonpath='https://{.spec.host}{"\n"}'
```

Later changes: push, then `oc start-build keel --follow`. The deployment restarts on the new image.

## Notes

- **One replica.** Analyses run in an in-process queue and all data is files on the `keel-data`
  volume (projects, floors, sources, decisions), mounted at `/app/data/processed`.
- **First start** downloads the RCRV sample drawing and builds the demo deck, so it takes a minute.
- **Accounts need MongoDB.** Nobody can log in until the app can reach a database. Add its address
  to the secret, then restart: `oc patch secret keel-ai -p '{"stringData":{"MONGODB_URI":"<address>"}}'`
  and `oc rollout restart deploy/keel`. This manifest does not run a database.
- **The login only guards the pages.** The `/api` routes do not check it, so anyone who can open the
  route can still call them to upload, change and delete. Keep the route internal, or put it behind
  your cluster's OAuth proxy, before sharing it.
