# Журнал изменений

## 2026-04-23

### Создано
- `ROBOT_GUIDE.md` — руководство по роботу: компоненты, все режимы работы, команды запуска

### Изменено
- `jetauto_ws/src/jetauto_example/scripts/tracker/object_tracking.py` — снижена скорость слежения за объектом:
  - PID дистанции: `1.8` → `0.8`
  - PID поворота: `0.005` → `0.002`
  - Макс. линейная скорость: `±0.3` → `±0.15` м/с
  - Макс. угловая скорость: `±1` → `±0.4` рад/с

### Исследовано
- Поворот камеры: отдельного серво нет, все 5 серво принадлежат руке-манипулятору.  
  Для изменения обзора — поворачивать весь корпус через `cmd_vel`.

### Обновлено
- `ROBOT_GUIDE.md` — добавлен раздел про поворот камеры в описание компонентов

---

## 2026-04-23 (продолжение)

### Создано
- `jetauto_ws/src/jetauto_example/scripts/cone_follow_node.py` — новая нода: автономное следование за красным конусом
  - Использует `color_detect` с `detect_type='rect'` (не 'circle' — конус прямоугольный)
  - PID steering по оси X кадра (центр 320 px)
  - Скорость вперёд: 0.12 м/с, остановка при bbox > 40 000 px²
- `jetauto_ws/src/jetauto_example/launch/cone_follow.launch` — launch-файл для запуска

### Обновлено
- `ROBOT_GUIDE.md` — добавлен раздел "0. Следование за красным конусом" с параметрами и описанием

---

## 2026-04-23 (продолжение 2)

### Исправлено
- `ROBOT_GUIDE.md` — исправлена ошибка: камера НЕ жёстко закреплена.
  Камера стоит на моторизованном шарнире с двумя PWM-серво (GPIO 13 и 12).
  Ранее написал "серво нет" — это было неверно.

### Исследовано
- PWM-серво: `jetauto_sdk/pwm_servo.py`, управление через `Jetson.GPIO`
  - servo=1 → GPIO 13 (pan)
  - servo=2 → GPIO 12 (tilt)
  - Диапазон 500–2500 мкс, центр 1500
  - Демо: `jetauto_example/scripts/jetauto_adapter_example/pwm_servo/two_pwm_servo_demo.py`

---

## [2026-04-30] v0.1.0 — Реализован MCP сервер и robot_api на роботе
### Added
- `.claude/mcp_server.py` — MCP сервер (7 инструментов: robot_move, read_sensors, get_camera_snapshot, run_diagnostic, emergency_stop, update_changelog, deploy_file)
- `.claude/config.py` — константы подключения (ROBOT, таймауты, пути)
- `.claude/mcp_config.json` — конфигурация регистрации MCP сервера
- `robot_api/move.py` — управление моторами через CLI, stub-режим если железо недоступно
- `robot_api/sensors.py` — ультразвук, IMU, батарея; заглушки с реалистичными данными
- `robot_api/camera.py` — захват JPEG через OpenCV, placeholder если камера недоступна
- `robot_api/diagnostic.py` — CPU, RAM, диск, температура, батарея через psutil
- `robot_api/changelog.py` — запись в ~/CHANGELOG.md на роботе
- `scripts/setup_robot.sh` — автоматический деплой robot_api на робота

---

## [2026-05-02] v0.3.1 — move.py доработан; recorder интегрирован с set_velocity
### Fixed
- `robot_api/move.py`:
  - `move()` теперь возвращает `speed_left`, `speed_right`, `vx`, `vy` в dict
  - Добавлен параметр `turn: float = 0.0` для диагонального движения
  - Добавлен параметр `blocking: bool = False` — CLI вызывает с `blocking=True`, recorder с `False`
  - Добавлена `set_velocity(speed_left, speed_right)` — прямое управление колёсами для recorder
  - Добавлена `stop_motors()` — безусловная остановка
  - `_get_chassis()` кеширует экземпляр Board, избегая повторного reset-to-zero
  - Добавлена константа `WHEEL_BASE = 0.15`
- `recorder/dataset_recorder.py`:
  - Импортирует `set_velocity` / `stop_motors` из `robot_api.move` (stub при недоступности)
  - WASD-маппинг использует точные значения: W+A→(0.12, 0.4), W+D→(0.4, 0.12)
  - `record_frame()` получает `speed_left`/`speed_right` из ответа `set_velocity()`
  - KEY_HOLD_SEC=0.15 — таймаут удержания клавиши для детекции диагоналей
  - `stop_motors()` в finally блоке обоих режимов

---

## [2026-05-02] v0.3.0 — Dataset Recorder (openpilot-стиль сбор данных)
### Added
- `recorder/dataset_recorder.py` — синхронная запись кадров и команд моторов для обучения автопилота
  - `DatasetRecorder` класс: start/stop/record_frame/get_stats, queue-based CSV запись в отдельном потоке
  - Структура сессии: `data/raw/session_YYYYMMDD_HHMMSS/` с frames/, controls.csv, meta.json, dataset.h5
  - CLI: `record` (WASD + headless `--duration N`), `finalize` (→HDF5), `stats`, `preview`
  - HDF5 структура: frames (N,120,160,3), speed_left/right, timestamp_ns, ultrasonic_cm
  - Заглушки: серый кадр при недоступной камере, stub-режим при отсутствии платы
  - Защита диска: автостоп при <100 MB свободного места; SIGTERM/Ctrl-C без потери данных
  - Совместимость с Python 3.6 (Jetson Nano Ubuntu 18.04)
- Протестировано: 99 кадров, 10.0 fps, controls.csv ✓, dataset.h5 ✓

---

## [2026-05-01] v0.2.0 — Улучшенные контроллеры + телеоп WASD
### Added
- `teleop.py` — единый финальный телеоп (заменяет my_teleop.py и teleop_key_control.py): WASD+QE движение, IJK0 камера, FirstOrderFilter с раздельными RC для разгона и торможения
- `PIDController` (inline) — PID с anti-windup и D-членом, вместо P-only из jetauto_sdk
- `FirstOrderFilter` (inline) — LP-фильтр на скорости, убирает рывки
### Changed
- `cone_follow_node.py` — добавлен поворот корпуса через angular.z (раньше следила только камера), скорость пропорциональна расстоянию до конуса, state machine LOST/TRACKING/NEAR
- `object_tracking.py` — дистанционный PID с anti-windup и I/D членами, фильтр на linear.x, freeze_integrator в мёртвой зоне ±10 см
