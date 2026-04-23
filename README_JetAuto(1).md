# Руководство по работе с роботом Hiwonder JetAuto

## Содержание
1. [Описание робота](#описание-робота)
2. [Подключение к роботу](#подключение-к-роботу)
3. [Порядок запуска](#порядок-запуска)
4. [Настройка алиасов (автозапуск команд)](#настройка-алиасов)
5. [Построение карты (SLAM)](#построение-карты-slam)
6. [Настройка RViz](#настройка-rviz)
7. [Управление роботом](#управление-роботом)
8. [Сохранение карты](#сохранение-карты)
9. [Устранение типичных ошибок](#устранение-типичных-ошибок)
10. [Справочник команд](#справочник-команд)

---

## Описание робота

**Hiwonder JetAuto** — мобильная робототехническая платформа на базе NVIDIA Jetson Nano.

| Компонент | Описание |
|-----------|----------|
| Компьютер | NVIDIA Jetson Nano (4GB RAM, 128 CUDA ядер) |
| Колёса | Меканум — движение в любом направлении (вперёд, вбок, по диагонали) |
| LiDAR | Slamtec A1 — лазерный сканер 360°, минимальная дистанция 15 см |
| Камера | Orbbec Astra Pro Plus — RGB + глубина |
| Микрофон | Линейка iFlyTek — голосовое управление |
| ОС | Ubuntu 18.04 + ROS Melodic |
| Wi-Fi | Точка доступа `HW_JetAuto_...`, IP: `192.168.149.1` |

---

## Подключение к роботу

### Шаг 1 — Подключись к Wi-Fi робота
- Включи робота, подожди 20–30 секунд
- Найди сеть `HW_JetAuto_...` или `JetAuto_...`
- **Пароль Wi-Fi:** `12345678`

### Шаг 2 — Подключись по SSH
```bash
ssh jetauto@192.168.149.1
```
- **Пароль:** `jetauto` (символы при вводе не отображаются — это нормально)
- Если спросит `yes/no` — введи `yes`

### Шаг 3 — Подключись через NoMachine (для графики)
- Скачай NoMachine: [nomachine.com](https://www.nomachine.com)
- Подключись к Wi-Fi робота
- Введи IP: `192.168.149.1`
- **Пароль:** `hiwonder`

> **Правило:** SSH — для всех текстовых команд. NoMachine — только для RViz и графических приложений.

---

## Порядок запуска

> **Важно:** всегда соблюдай этот порядок. Без bringup ничего не работает.

### Терминал 1 (SSH) — Базовый запуск
```bash
roslaunch jetauto_bringup bringup.launch
```
Подожди 10–15 секунд. LiDAR должен начать вращаться. Оставь это окно открытым.

### Терминал 2 (SSH) — Проверка
```bash
rostopic list | grep -E "scan|tf|map"
```
Должны появиться `/scan`, `/tf`, `/map`.

### Терминал 3 (SSH) — SLAM (построение карты)
```bash
roslaunch jetauto_slam slam.launch
```

### Терминал в NoMachine — Визуализация
```bash
roslaunch jetauto_slam rviz_slam.launch
```

### Терминал 4 (SSH) — Пульт управления
```bash
python ~/Desktop/my_teleop.py
```

---

## Настройка алиасов

Алиасы позволяют запускать длинные команды одним словом. Настраивается один раз.

```bash
nano ~/.bashrc
```

Добавь в конец файла:
```bash
# Быстрые команды для JetAuto
alias robot_start="sudo systemctl stop start_app_node.service; roslaunch jetauto_bringup bringup.launch"
alias robot_slam="roslaunch jetauto_slam slam.launch"
alias robot_rviz="roslaunch jetauto_slam rviz_slam.launch"
alias robot_save="rosrun map_server map_saver map:=/map -f /home/jetauto/my_map"
alias robot_drive="python ~/Desktop/smart_teleop.py"
alias robot_check="rostopic list | grep -E 'scan|tf|map'"
```

Сохрани (Ctrl+O → Enter → Ctrl+X) и примени:
```bash
source ~/.bashrc
```

После этого вместо длинных команд используй:
```bash
robot_start   # Терминал 1 — запуск железа
robot_slam    # Терминал 2 — картография
robot_rviz    # В NoMachine — визуализация
robot_drive   # Терминал 3 — пульт
robot_save    # Терминал 4 — сохранить карту
robot_check   # Проверить топики
```

---

## Построение карты (SLAM)

### Алгоритм работы
```
LiDAR сканирует → /scan → gmapping строит карту → /map → RViz отображает
```

### Советы для хорошей карты
- Езди **очень медленно** — максимум 1–2 нажатия W на пульте (0.1–0.15 м/с)
- Держи дистанцию от стен **30 см — 2 метра** (ближе 15 см LiDAR не видит)
- Объезжай комнату сначала **по периметру вдоль стен**, потом внутрь
- Возвращайся в уже знакомые места — это помогает gmapping "склеить" карту точнее
- Добавь объекты в комнату (стулья, коробки) — на гладком полу колёса буксуют
- После запуска slam подожди **5–10 секунд** стоя на месте перед началом движения

### Конкретные правила для сканирования местности

**Скорость** — максимум одно нажатие W (0.05–0.1 м/с). Это очень медленно, почти пешком.

**Дистанция от стен** — держись на расстоянии 30–60 см. Ближе 15 см LiDAR слепой, дальше 3 метров теряет точность.

**Повороты** — никогда не крути на месте. Поворачивай в движении — нажимай W и Q одновременно, робот будет плавно поворачивать на ходу.

**Перекрытие** — возвращайся в уже знакомые места. Это самое важное — gmapping "узнаёт" место и корректирует накопившуюся ошибку.

**Паузы** — после каждого нового участка останавливайся на 2–3 секунды. Gmapping успевает обработать данные.

---
### Признаки хорошей карты
- Чёрные линии стен — чёткие и непрерывные
- Белое пространство — чистое, без артефактов
- Углы комнаты — прямые ~90°
- Серых (неизвестных) зон — менее 20%

---

## Настройка RViz

### Быстрый способ (рекомендуется)
Запускай всегда через:
```bash
roslaunch jetauto_slam rviz_slam.launch
```
Откроется RViz с уже настроенными параметрами.

### Ручная настройка (если RViz открылся пустым)

**Шаг 1 — Fixed Frame**
- В левой панели найди `Global Options → Fixed Frame`
- Измени значение на `map`
- Если появится ошибка "does not exist" — смени на `lidar_frame`

**Шаг 2 — Добавь карту**
- Нажми кнопку `Add` (снизу левой панели)
- Выбери `Map`
- В поле `Topic` укажи `/map`
- В поле `Color Scheme` выбери `map`

**Шаг 3 — Добавь лазер**
- Нажми `Add` → выбери `LaserScan`
- `Topic`: `/scan`
- `Style`: `Flat Squares`
- `Size (m)`: `0.05`

**Шаг 4 — Добавь модель робота**
- Нажми `Add` → выбери `RobotModel`
- Параметры оставь по умолчанию

### Правильные параметры RViz

| Параметр | Значение |
|----------|----------|
| Fixed Frame | `map` |
| Background Color | `48; 48; 48` (тёмный) |
| Frame Rate | `30` |
| Map → Topic | `/map` |
| Map → Color Scheme | `map` |
| LaserScan → Topic | `/scan` |
| LaserScan → Style | `Flat Squares` |
| LaserScan → Size (m) | `0.05` |
| LaserScan → Alpha | `1` |

### Если Fixed Frame выдаёт ошибку
```bash
# Проверь доступные фреймы
rostopic echo /scan --noarr -n 1 | grep frame_id
```
Используй то название что выведет команда.

## Управление роботом

### Пульт управления (smart_teleop.py)

```
W — ускориться вперёд
S — ускориться назад
A — ускориться влево (боком)
D — ускориться вправо (боком)
Q — вращение влево
E — вращение вправо
Пробел — экстренная остановка
Ctrl+C — выход (робот остановится автоматически)
```

> Каждое нажатие добавляет скорость на 0.05 м/с. Три нажатия W = 0.15 м/с.
> Противоположная кнопка уменьшает скорость, не разворачивает резко.

### Прямое управление через терминал
```bash
# Вперёд
rostopic pub /cmd_vel geometry_msgs/Twist '{linear: {x: 0.2}}' -r 10

# Остановить (всегда после движения!)
rostopic pub /cmd_vel geometry_msgs/Twist '{linear: {x: 0.0}}' -1
```

> **Важно:** Ctrl+C останавливает публикацию, но не робота. Всегда отправляй нули отдельной командой.

---

## Сохранение карты

Когда карта в RViz выглядит хорошо:
```bash
rosrun map_server map_saver map:=/map -f /home/jetauto/my_map
```

Дождись сообщения `Done`. На роботе появятся два файла:
- `/home/jetauto/my_map.pgm` — изображение карты
- `/home/jetauto/my_map.yaml` — метаданные (разрешение, размер, начало координат)

### Скопировать карту на свой ПК
```bash
scp jetauto@192.168.149.1:/home/jetauto/my_map.pgm ./
scp jetauto@192.168.149.1:/home/jetauto/my_map.yaml ./
```

---

## Устранение типичных ошибок

### Ошибка: `Address already in use` / порт 11311 занят
```bash
sudo killall -9 rosmaster roslaunch python python3
sudo systemctl stop start_app_node.service
roslaunch jetauto_bringup bringup.launch
```

### Ошибка: `web_video_server` — порт 8080 занят
```bash
sudo pkill -f web_video_server
```
Можно игнорировать — на работу LiDAR и моторов не влияет.

### Ошибка: `Resource busy` — порт USB занят
```bash
sudo fuser -k /dev/ttyUSB0
sudo fuser -k /dev/ttyACM0
roslaunch jetauto_bringup bringup.launch
```

### Ошибка: RViz — `Fixed Frame does not exist`
- Смени Fixed Frame с `map` на `lidar_frame`
- Или убедись что запущен `slam.launch`

### Ошибка: карта не сохраняется (`Waiting for the map...`)
- Подвигай робота пультом — gmapping обновит карту
- Или укажи топик явно:
```bash
rosrun map_server map_saver map:=/map -f /home/jetauto/my_map
```

### Робот не едет после команды
1. Убедись что bringup запущен: `rostopic list | grep cmd_vel`
2. Проверь заряд батареи (пищание = низкий заряд)
3. Перезапусти bringup если завис

### Робот вращается в RViz хотя стоит на месте
- Одометрия врёт из-за скольжения колёс
- Перезапусти slam: Ctrl+C → `roslaunch jetauto_slam slam.launch`
- Поставь робота на нескользкую поверхность

### Зуммер пищит
Низкий заряд батареи. Немедленно:
1. Останови все программы (Ctrl+C)
2. Выключи робота
3. Заряди аккумулятор (2–3 часа)

---

## Справочник команд

### Подключение
| Действие | Команда |
|----------|---------|
| SSH подключение | `ssh jetauto@192.168.149.1` |
| Настройка окружения | `source ~/.bashrc` |

### Запуск модулей
| Модуль | Команда | Терминал |
|--------|---------|----------|
| Базовый запуск (всегда первым) | `roslaunch jetauto_bringup bringup.launch` | SSH |
| SLAM — построение карты | `roslaunch jetauto_slam slam.launch` | SSH |
| SLAM + RViz вместе | `roslaunch jetauto_slam rviz_slam.launch` | NoMachine |
| Загрузка готовой карты | `roslaunch jetauto_navigation navigation.launch map_name:=/home/jetauto/my_map` | SSH |
| Пульт управления | `python ~/Desktop/smart_teleop.py` | SSH |

### Диагностика
| Действие | Команда |
|----------|---------|
| Все топики | `rostopic list` |
| Проверить LiDAR | `rostopic list \| grep scan` |
| Проверить TF | `rostopic list \| grep tf` |
| Данные лазера | `rostopic echo /scan --noarr` |
| Частота карты | `rostopic hz /map` |
| Список узлов | `rosnode list` |
| Доступные launch-файлы | `ls $(rospack find jetauto_slam)/launch/` |

### Управление картой
| Действие | Команда |
|----------|---------|
| Сохранить карту | `rosrun map_server map_saver map:=/map -f /home/jetauto/my_map` |
| Скопировать карту на ПК | `scp jetauto@192.168.149.1:/home/jetauto/my_map.pgm ./` |

### Устранение неполадок
| Действие | Команда |
|----------|---------|
| Убить все процессы ROS | `sudo killall -9 rosmaster roslaunch python python3` |
| Остановить автосервис | `sudo systemctl stop start_app_node.service` |
| Освободить USB порт | `sudo fuser -k /dev/ttyUSB0` |
| Убить video server | `sudo pkill -f web_video_server` |
| Очистить логи | `rm -rf ~/.ros/log/*` |

---

## Стандартный сеанс работы

```
1. Включить робота → подождать 20 сек
2. Подключиться к Wi-Fi HW_JetAuto_...
3. SSH: robot_start          (ждать 10 сек, LiDAR начнёт крутиться)
4. SSH: robot_slam            (запустить картографию)
5. NoMachine: robot_rviz      (открыть визуализацию)
6. SSH: robot_drive           (запустить пульт)
7. Медленно объехать комнату по периметру
8. SSH: robot_save            (сохранить карту, дождаться Done)
9. Ctrl+C везде → выключить робота
```

---

*Робот: Hiwonder JetAuto | ОС: Ubuntu 18.04 | ROS: Melodic | IP: 192.168.149.1*
