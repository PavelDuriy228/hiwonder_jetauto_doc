# JetAuto — Руководство по роботу

## Подключение

```bash
# SSH
ssh jetauto@192.168.3.100

# Проверка связи
ssh jetauto@192.168.3.100 "echo ok"
```

Для GUI-приложений (OpenCV окна, RViz) — **NoMachine** на `192.168.3.100:4000`.

---

## Платформа

| | |
|---|---|
| Компьютер | NVIDIA Jetson Nano (aarch64) |
| ОС | Ubuntu 18.04 LTS |
| ROS | Melodic |
| Python | 3.6.9 |
| CUDA | 10.2 |

---

## Основные компоненты

### Движение
- **Меканум-колёса** — 4 колеса, может ехать в любом направлении (вбок, по диагонали)
- Топик управления: `/jetauto_controller/cmd_vel` (тип `geometry_msgs/Twist`)

### Сенсоры
| Сенсор | Назначение | Топики ROS |
|---|---|---|
| Orbbec Astra Pro | RGB + глубина | `/camera/rgb/image_raw`, `/camera/depth/image_raw` |
| Лидар (RPLidar / YDLidar) | 2D карта окружения | `/scan` |
| IMU MPU-6050 | Ориентация в пространстве | `/imu/data` |
| USB-камера `/dev/video0` | Дополнительная камера | — |

### Манипулятор
- Рука с 5 серво-приводами (шина `/dev/ttyTHS1`, IDs 1–5): joint1–joint4 + захват (gripper)
- Кинематика: `jetauto_arm_kinematics`
- Управление: топик `servo_controllers/port_id_1/multi_id_pos_dur`

### Камера — поворот (PWM-серво)
Камера установлена на моторизованном шарнире и управляется двумя **PWM-серво** через GPIO Jetson Nano:

| Серво | GPIO (BCM) | Ось |
|---|---|---|
| `PWMServo(1)` | 13 | pan (горизонталь) |
| `PWMServo(2)` | 12 | tilt (вертикаль) |

Диапазон позиций: `500–2500` мкс, центр = `1500`.

**Быстрый тест (камера качается туда-обратно):**
```bash
cd ~/jetauto_ws/src/jetauto_example/scripts/jetauto_adapter_example/pwm_servo/
python3 two_pwm_servo_demo.py
```

**Управление из Python:**
```python
from jetauto_sdk.pwm_servo import PWMServo

pan  = PWMServo(1)  # горизонталь
tilt = PWMServo(2)  # вертикаль
pan.start()
tilt.start()

pan.set_position(1500)   # центр
tilt.set_position(1300)  # вниз
```

SDK: `jetauto_sdk/pwm_servo.py`

### Голос
- Офлайн распознавание речи iFlytek (пакет `xf_mic_asr_offline`)

---

## Что умеет делать

### 0. Следование за красным конусом ⭐
Робот обнаруживает красный конус и едет за ним. Останавливается когда конус близко (~40 000 px² bbox).

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example cone_follow.launch
```

**Параметры (в `cone_follow_node.py`):**
| Переменная | Значение | Описание |
|---|---|---|
| `MIN_AREA` | 800 px² | минимальный размер конуса в кадре чтобы начать движение |
| `STOP_AREA` | 40 000 px² | размер bbox при котором робот останавливается |
| `twist.linear.x` | 0.12 м/с | скорость движения вперёд |
| `PID(0.003, ...)` | P=0.003 | агрессивность поворота к конусу |

**Как работает:**
1. `color_detect` находит красные прямоугольные области (`detect_type='rect'`)
2. PID поворачивает робота чтобы центр конуса совпал с центром кадра (320 px)
3. Едет вперёд со скоростью 0.12 м/с пока `area < STOP_AREA`

**Файлы:**
- `jetauto_example/scripts/cone_follow_node.py`
- `jetauto_example/launch/cone_follow.launch`

---

### 1. Слежение за произвольным объектом
Выбираешь объект мышью — робот едет за ним, держа дистанцию ~100 см.

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example object_tracking.launch
```

**Управление:** левая кнопка мыши — нарисовать рамку вокруг объекта, правая — сброс.  
**Файл:** `jetauto_example/scripts/tracker/object_tracking.py`

> Параметры скорости (после тюнинга):
> - Макс. линейная скорость: ±0.15 м/с
> - Макс. угловая скорость: ±0.4 рад/с
> - PID дистанции: P=0.8, PID поворота: P=0.002

---

### 2. Слежение по цвету
Робот находит объект заданного цвета и едет за ним (+ отслеживает рукой-манипулятором).

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example color_track_node.launch
```

Цвет по умолчанию — красный. Менять через ROS-сервис:
```bash
rosservice call /color_track_node/set_color "data: 'blue'"
# доступные цвета: red, green, blue
```

**Файл:** `jetauto_example/scripts/color_track/color_track_node.py`

---

### 3. Детекция объектов YOLOv5 (TensorRT)
Готовые обученные модели, работают на GPU Jetson Nano.

| Модель | Что распознаёт |
|---|---|
| `garbage_classification_320s_6_2.engine` | Мусор по категориям |
| `traffic_signs_640s_7_0.engine` | Дорожные знаки |

```bash
# Классификация мусора
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example garbage_classification.launch

# Дорожные знаки
roslaunch jetauto_example yolov5_detect.launch
```

**Файл:** `jetauto_example/scripts/yolov5_detect/yolov5_node.py`

---

### 4. MediaPipe — распознавание человека
```bash
source ~/jetauto_ws/devel/setup.bash
rosrun jetauto_example face_detect.py      # лицо
rosrun jetauto_example hand.py             # руки
rosrun jetauto_example pose.py             # поза тела
rosrun jetauto_example holistic.py         # всё вместе
rosrun jetauto_example self_segmentation.py # сегментация фона
```

**Файлы:** `jetauto_example/scripts/mediapipe_example/`

---

### 5. Управление жестами рук
Робот едет в направлении, которое показывает рука.

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example hand_gesture_control_node.launch
```

**Файл:** `jetauto_example/scripts/hand_gesture_control/hand_gesture_control_node.py`

---

### 6. Управление с клавиатуры и джойстика
```bash
source ~/jetauto_ws/devel/setup.bash
# Клавиатура
rosrun jetauto_peripherals teleop_key_control.py

# Джойстик
rosrun jetauto_peripherals joystick_control.py
```

---

### 7. Сортировка объектов по цвету
Робот рукой берёт объект и сортирует по цвету в нужную зону.

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example color_sorting_node.launch
```

**Файл:** `jetauto_example/scripts/color_sorting/color_sorting_node.py`

---

### 8. Автопилот по разметке
Робот едет вдоль нарисованной линии на полу.

```bash
source ~/jetauto_ws/devel/setup.bash
roslaunch jetauto_example self_driving.launch
```

**Файл:** `jetauto_example/scripts/self_driving/self_driving.py`

---

### 9. Построение карты (SLAM)
Поддерживаются алгоритмы: **gmapping**, cartographer, hector, karto, rtabmap, frontier, rrt_exploration.

```bash
source ~/jetauto_ws/devel/setup.bash
# Построение карты (gmapping по умолчанию)
roslaunch jetauto_slam slam.launch slam_methods:=gmapping

# Визуализация в RViz
roslaunch jetauto_slam rviz_slam.launch
```

Сохранить карту:
```bash
rosrun map_server map_saver -f ~/my_map
```

Готовая карта уже есть: `~/map_02.pgm` + `~/map_02.yaml`

---

### 10. Автономная навигация по карте
Робот сам строит маршрут и объезжает препятствия (стек: ROS Navigation / move_base).

```bash
source ~/jetauto_ws/devel/setup.bash
# Запуск навигации с готовой картой
roslaunch jetauto_navigation navigation.launch map:=$HOME/map_02.yaml

# Визуализация и задание цели в RViz
roslaunch jetauto_navigation rviz_navigation.launch
```

Цель задаётся кнопкой **2D Nav Goal** в RViz.

**Файлы:** `jetauto_navigation/launch/`

---

## Структура workspace

```
~/jetauto_ws/src/
├── jetauto_bringup/        # базовый запуск робота
├── jetauto_controller/     # контроллер колёс
├── jetauto_driver/         # SDK, серво, кинематика руки
├── jetauto_example/        # все примеры (см. выше)
├── jetauto_slam/           # построение карты
├── jetauto_navigation/     # автономная навигация
├── jetauto_peripherals/    # камера, лидар, IMU
├── jetauto_app/            # приложения
├── jetauto_interfaces/     # кастомные ROS-сообщения
├── xf_mic_asr_offline/     # голосовое распознавание
└── third_party/            # cartographer, rplidar, astra и др.
```
