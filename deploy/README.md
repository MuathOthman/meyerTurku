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
- **Accounts need MongoDB.** `deploy/mongodb.yaml` runs one inside the project, reachable only by
  the app. Create its secret once, with a random password, then apply it before the app:
  ```bash
  pw=$(openssl rand -hex 24)
  oc create secret generic keel-mongo --from-literal=MONGO_INITDB_ROOT_USERNAME=keel \
    --from-literal=MONGO_INITDB_ROOT_PASSWORD=$pw \
    --from-literal=MONGODB_URI="mongodb://keel:$pw@mongodb:27017/?authSource=admin"
  oc apply -f deploy/mongodb.yaml
  ```
  To use a database elsewhere instead, put its address in `MONGODB_URI` in that secret.
- **The login only guards the pages.** The `/api` routes do not check it, so anyone who can open the
  route can still call them to upload, change and delete. Keep the route internal, or put it behind
  your cluster's OAuth proxy, before sharing it.
