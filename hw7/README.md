Я на всякий случай сделал hw7/.gitlab-ci.yml


docker compose -f docker-compose.blue.yml up -d --build
curl http://localhost:8080/health
curl -X POST http://localhost:8080/predict -H "Content-Type: application/json" -d '{"x":[5.1, 3.5, 1.4, 0.2]}'
docker compose -f docker-compose.green.yml up -d --build
curl http://localhost:8080/health
docker compose -f docker-compose.blue.yml up -d