# Деинсталляция Асси

Команды нужно выполнять из папки репозитория, пока в ней находится `docker-compose.yml`.

## 1. Удали Docker-ресурсы Асси

```bash
docker compose down -v --rmi all --remove-orphans
```

Команда удаляет контейнеры, сети, образы и именованные volumes Compose-проекта. Вместе с volumes удаляются PostgreSQL, данные Qdrant, загруженные материалы и кэш моделей.

Проверить, что Compose-контейнеры удалены:

```bash
docker compose ps --all
```

## 2. При необходимости очисти build cache

```bash
docker builder prune
```

> `docker builder prune` не ограничивается Асси: команда может удалить неиспользуемый кэш сборки других Docker-проектов. Перед удалением Docker покажет запрос подтверждения.

## 3. Удали репозиторий

Для нового клона стандартное имя папки — `Assi`. Если репозиторий был клонирован до переименования и локальная папка всё ещё называется `MLproject`, используй её фактическое имя вместо `Assi`.

macOS/Linux:

```bash
cd ..
rm -rf Assi
```

Windows PowerShell:

```powershell
Set-Location ..
Remove-Item -Recurse -Force .\Assi
```

После этого исходный код и Docker-ресурсы Асси будут удалены. Git, Docker Desktop и ресурсы других активных Docker-проектов останутся.

Проверить общее использование диска Docker:

```bash
docker system df
```
