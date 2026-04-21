up:
	docker compose up

build:
	docker compose up --build

down:
	docker compose down

clean:
	docker compose down -v

logs:
	docker compose logs -f

restart:
	docker compose down && docker compose up --build