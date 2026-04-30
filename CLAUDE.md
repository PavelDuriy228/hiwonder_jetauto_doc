# JetAuto — Claude Code Project

## Цель проекта
Превратить Hiwonder JetAuto в "Теслу":
автопилот, объезд препятствий, удержание полосы,
автопарковка, веб-дашборд телеметрии.

---

## Подключение
```bash
ssh jetauto@192.168.149.1   # ключ настроен, пароль не нужен
```

Быстрая проверка:
```bash
ssh jetauto@192.168.149.1 "echo ok && python3 --version"
```

---

## Структура проекта на роботе
~/jetauto_tesla/
├── move.py          # управление движением (скорость, поворот, стоп)
├── sensors.py       # ультразвук, IMU, энкодеры
├── camera.py        # захват видео, lane detection
├── autopilot.py     # основной цикл автопилота
├── status.py        # сбор телеметрии (CPU, батарея, скорость)
├── web_ui/          # веб-дашборд
└── logs/            # логи сессий

---

## Основные команды

### Проверка и диагностика
```bash
ssh jetauto@192.168.149.1 "ls ~/jetauto_tesla/"
ssh jetauto@192.168.149.1 "python3 ~/jetauto_tesla/status.py"
ssh jetauto@192.168.149.1 "vcgencmd measure_temp"      # температура
ssh jetauto@192.168.149.1 "free -h && df -h"           # память/диск
```

### Запуск модулей
```bash
ssh jetauto@192.168.149.1 "python3 ~/jetauto_tesla/autopilot.py"
ssh jetauto@192.168.149.1 "python3 ~/jetauto_tesla/camera.py --preview"
```

### Остановка (ВСЕГДА перед отключением!)
```bash
ssh jetauto@192.168.149.1 "python3 ~/jetauto_tesla/move.py --stop"
```

---

## Правила разработки

### Безопасность — ОБЯЗАТЕЛЬНО
- Каждый скрипт движения должен иметь `try/finally` с командой стоп
- Перед тестом движения: убедиться, что робот на полу и пространство свободно
- Максимальная скорость при разработке: 30% от максимума
- Никогда не запускать autopilot.py без физической кнопки стоп под рукой

### Стиль кода
- Python 3, type hints обязательны
- Каждая функция — docstring с описанием и примером
- Логирование через `logging`, не `print`
- Конфигурация через `config.yaml`, не хардкод

---

## CHANGELOG — обязательное правило

**Каждое значимое изменение должно быть записано в CHANGELOG.md.**

Формат записи:
```markdown
## [YYYY-MM-DD] vX.Y — Короткое название
### Добавлено
- Описание новой функции
### Изменено  
- Что было изменено и почему
### Исправлено
- Какой баг исправлен
```

Claude Code должен обновлять CHANGELOG.md после каждой сессии разработки.
Команда для записи (пример):
```bash
ssh jetauto@192.168.149.1 "echo '## [$(date +%Y-%m-%d)] — ...' >> ~/CHANGELOG.md"
```

---

## Контекст

- Краткая документация: `README_JetAuto(1).md` и `ROBOT_GUIDE.md`
- История чатов первой настройки: google_ai_studio

---

## MCP сервер

Регистрация (один раз):
```bash
claude mcp add jetauto -- python3 .claude/mcp_server.py
```

Деплой robot_api на робота:
```bash
bash scripts/setup_robot.sh
```

Запуск: `claude mcp add jetauto -- python3 .claude/mcp_server.py`

Доступные инструменты:
- `robot_move(direction, speed, duration)` — движение
- `read_sensors()` — данные сенсоров (JSON)
- `get_camera_frame()` — снимок с камеры (base64)
- `run_diagnostic()` — полный статус системы
- `update_changelog(entry)` — записать в CHANGELOG.md на ПК и на роботе
- `emergency_stop()` — АВАРИЙНАЯ ОСТАНОВКА, всегда работает

## Правило для Claude Code
После каждого изменения файлов — вызывать update_changelog().
Перед каждым тестом движения — вызывать read_sensors() и убедиться, что батарея > 20%.

## Tesla-фичи — дорожная карта

| Фича | Статус | Файл |
|------|--------|------|
| Базовое движение (WASD) | ☐ | move.py |
| Чтение сенсоров | ☐ | sensors.py |
| Стрим с камеры | ☐ | camera.py |
| Детекция полосы (lane keeping) | ☐ | autopilot.py |
| Объезд препятствий | ☐ | autopilot.py |
| Веб-дашборд телеметрии | ☐ | web_ui/ |
| Автопарковка | ☐ | autopilot.py |
| Голосовые команды | ☐ | voice.py |