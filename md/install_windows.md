# Установка окружения на Windows

Этот файл нужен только для компьютера, на котором ещё нет Docker и Git. Для обычного запуска проекта Python, PostgreSQL, Qdrant и Node.js отдельно устанавливать не требуется.

После подготовки вернись к [быстрому запуску](start.md).

## 1. Проверь системные требования

Рекомендуемый вариант — Docker Desktop с backend `WSL 2`.

Проверь версию Windows:

1. Нажми `Win + R`.
2. Введи `winver`.
3. Убедись, что используется поддерживаемая 64-битная версия Windows 10 или Windows 11.

Также в BIOS/UEFI должна быть включена аппаратная виртуализация.

Официальная инструкция Docker:

- <https://docs.docker.com/desktop/setup/install/windows-install/>

## 2. Установи или обнови WSL 2

Открой PowerShell **от имени администратора**:

```powershell
wsl --install
wsl --update
```

После установки может потребоваться перезагрузка.

Проверка:

```powershell
wsl --version
wsl --status
```

Если команда `wsl --version` не показывает версию, WSL нужно обновить.

## 3. Установи Docker Desktop

1. Скачай Docker Desktop с официальной страницы.
2. Запусти `Docker Desktop Installer.exe`.
3. Оставь включённым использование `WSL 2`.
4. Заверши установку и перезагрузи компьютер, если это предложено.
5. Запусти Docker Desktop.
6. Используй режим Linux containers.

Docker Desktop уже включает Docker Engine, Docker CLI, Docker Build и Docker Compose. Отдельно устанавливать `docker-compose` не нужно.

Проверка в PowerShell:

```powershell
docker --version
docker compose version
docker run --rm hello-world
```

<!-- TODO: вставить скрин Docker Desktop со статусом Engine running -->

## 4. Установи Git

Проверка:

```powershell
git --version
```

Установить через `winget`:

```powershell
winget install --id Git.Git -e --source winget
```

Либо используй официальный установщик:

- <https://git-scm.com/install/windows>

Закрой и заново открой PowerShell, затем повтори:

```powershell
git --version
```

Git не обязателен, если репозиторий скачивается через **Code → Download ZIP**.

## 5. Скачай и запусти проект

```powershell
git clone https://github.com/ssd2008/Assi.git
Set-Location Assi
docker compose up --build
```

После запуска открой:

```text
http://127.0.0.1:3000
```

## Где хранить проект

Для простого запуска можно хранить проект в обычной папке Windows.

Для активной разработки через WSL Docker рекомендует хранить исходники внутри Linux-файловой системы WSL, а не в `/mnt/c/...`: это обычно быстрее при большом количестве файлов.

## Возможные ограничения

### Docker сообщает, что виртуализация выключена

Включи Intel VT-x или AMD-V/SVM в BIOS/UEFI. Название настройки зависит от производителя компьютера.

### Docker работает с Windows containers

Переключи Docker Desktop на Linux containers. Проект использует Linux-образы.

### WSL потребляет слишком много памяти

Полностью завершить WSL:

```powershell
wsl --shutdown
```

Затем снова запусти Docker Desktop.

### Порт занят

Проверка порта, например `8000`:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

Дальнейшая диагностика: [Типовые проблемы](troubleshooting.md).
