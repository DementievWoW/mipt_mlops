**Выбран Redis** (Lists + Pub/Sub) — лёгкий, быстрый и удовлетворяющий требованиям задания.
Он используется для передачи заданий от Gateway к Worker.

k3d cluster create hw6-ml-pipeline

kubectl cluster-info
kubectl get nodes

k3d-hw6-ml-pipeline-server-0   Ready    control-plane,master   18s   v1.31.5+k3s1

docker pull redis:7-alpine
k3d image import redis:7-alpine -c hw6-ml-pipeline

FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime
что бы торч полгода не ставить 

docker build -t grpc-gateway:latest -f Dockerfile.gateway .
docker build -t grpc-worker:latest -f Dockerfile.worker .

k3d image import grpc-gateway:latest -c hw6-ml-pipeline
k3d image import grpc-worker:latest -c hw6-ml-pipeline

helm upgrade --install grpc-inference ./grpc-inference

(gpu_env) toxic@toxic-Lenovo-Legion-S7-15ARH5:~/mipt/mipt_mlops/hw6/helm$ kubectl get po
NAME                                     READY   STATUS    RESTARTS   AGE
grpc-inference-gateway-d84989b44-74rrh   1/1     Running   0          34s
grpc-inference-redis-6f758f8969-4dfbf    1/1     Running   0          34s
grpc-inference-worker-84fc997986-8dkkx   1/1     Running   0          34s

kubectl get pods
kubectl logs deployment/grpc-inference-gateway
kubectl logs deployment/grpc-inference-worker

kubectl port-forward service/grpc-gateway-service 50051:50051
python client.py

(gpu_env) toxic@toxic-Lenovo-Legion-S7-15ARH5:~/mipt/mipt_mlops/hw6$ python client.py
Text: Привет, embedding[:3] = [0.7226621508598328, -0.37929272651672363, 0.323921799659729]...
Text: Как дела?, embedding[:3] = [-0.5463643074035645, -0.5490291714668274, -0.16587616503238678]...
Text: Машинное обучение, embedding[:3] = [1.3255523443222046, -0.13113005459308624, -0.4205923080444336]...