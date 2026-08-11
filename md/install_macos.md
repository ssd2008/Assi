# Установка окружения на macOS

Этот файл нужен только для компьютера, на котором ещё нет Docker и Git. Для обычного запуска проекта Python, PostgreSQL, Qdrant и Node.js отдельно устанавливать не требуется.

После подготовки вернись к [быстрому запуску](start.md).

## 1. Проверь архитектуру Mac

Открой меню **Apple → Об этом Mac** и посмотри поле `Chip` или `Processor`:

- `Apple M1`, `M2`, `M3`, `M4` и новее — Apple silicon;
- `Intel` — Intel Mac.

Это важно при выборе установщика Docker Desktop.

## 2. Установи Docker Desktop

Официальная инструкция:

- <https://docs.docker.com/desktop/setup/install/mac-install/>

Порядок установки:

1. Скачай Docker Desktop для своей архитектуры.
2. Открой `Docker.dmg`.
3. Перетащи Docker в папку `Applications`.
4. Запусти `Docker.app`.
5. Прими лицензионное соглашение.
6. Выбери рекомендуемые настройки.
7. Дождись статуса, что Docker Engine запущен.

Docker Desktop уже включает Docker Engine, Docker CLI, Docker Build и Docker Compose. Отдельно устанавливать `docker-compose` не нужно.

Проверка в Terminal:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

Если все команды выполняются без ошибок, Docker готов.

<!-- TODO: вставить скрин Docker Desktop со статусом Engine running -->

## 3. Установи Git

Сначала проверь:

```bash
git --version
```

Если Git отсутствует, macOS обычно предложит установить Xcode Command Line Tools. Их можно запустить вручную:

```bash
xcode-select --install
```

Официальные варианты установки Git:

- <https://git-scm.com/install/mac>

После установки снова проверь:

```bash
git --version
```

Git не обязателен, если репозиторий скачивается через **Code → Download ZIP**.

## 4. Скачай и запусти проект

```bash
git clone https://github.com/ssd2008/Assi.git
cd Assi
docker compose up --build
```

После запуска открой:

```text
http://127.0.0.1:3000
```

## Возможные ограничения

### Недостаточно памяти или Docker зависает

ML-модели ресурсоёмкие. Закрой тяжёлые приложения и проверь настройки ресурсов Docker Desktop.

### Apple silicon и Rosetta

Основные Linux-контейнеры обычно работают без Rosetta. Docker рекомендует Rosetta 2 для совместимости с отдельными AMD64-инструментами. Установка:

```bash
softwareupdate --install-rosetta
```

Не устанавливай Rosetta без необходимости, если проект уже запускается.

### Порт занят

Проверить, какой процесс использует порт:

```bash
lsof -i :3000
lsof -i :8000
lsof -i :5432
lsof -i :6333
```

Дальнейшая диагностика: [Типовые проблемы](troubleshooting.md).
