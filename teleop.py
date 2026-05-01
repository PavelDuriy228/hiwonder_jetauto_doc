#!/usr/bin/env python3
# encoding: utf-8
# Ручное управление JetAuto через клавиатуру.
# Заменяет my_teleop.py и teleop_key_control.py.
#
# Движение:        Камера:
#       W               I
#  Q  A   D  E      J   K   L
#       S            0 — центр
#
#  W/S  — вперёд / назад
#  A/D  — поворот влево / вправо
#  Q/E  — стрейф влево / вправо
#  I/K  — камера вверх / вниз
#  J/L  — камера влево / вправо
#  0    — камера в центр
#  Ctrl-C — выход

import os
import sys
import select
import time
import rospy
from geometry_msgs.msg import Twist

if os.name == 'nt':
    import msvcrt

LIN_VEL  = 0.20   # м/с   максимальная линейная скорость
ANG_VEL  = 0.60   # рад/с максимальная угловая скорость
# Постоянная времени фильтра (сек): больше = плавнее, но медленнее отклик
RC_ACCEL = 0.20   # разгон
RC_BRAKE = 0.08   # торможение (быстрее для безопасности)

CAM_STEP    = 100
PAN_CENTER  = 1500
TILT_CENTER = 1500
PAN_MIN,  PAN_MAX  = 800, 2200
TILT_MIN, TILT_MAX = 800, 2200

LOOP_DT = 0.05    # 20 Hz основной цикл

BANNER = """
╔═══════════════════════════════════════╗
║        Управление JetAuto             ║
╠═══════════════════════════════════════╣
║  Движение:          Камера:           ║
║        W                 I            ║
║   Q  A   D  E        J   K   L        ║
║        S             0 — в центр      ║
╠═══════════════════════════════════════╣
║  W/S  — вперёд / назад                ║
║  A/D  — поворот влево / вправо        ║
║  Q/E  — стрейф влево / вправо         ║
║  I/K  — камера вверх / вниз           ║
║  J/L  — камера влево / вправо         ║
║  Ctrl-C — выход                       ║
╚═══════════════════════════════════════╝
"""


class FirstOrderFilter:
    """Экспоненциальный LP-фильтр с разными RC для разгона и торможения.

    Источник идеи: openpilot/common/filter_simple.py
    """

    def __init__(self, x0=0.0):
        self.x = float(x0)
        self.alpha_accel = LOOP_DT / (RC_ACCEL + LOOP_DT)
        self.alpha_brake = LOOP_DT / (RC_BRAKE + LOOP_DT)

    def update(self, target):
        # Используем более быстрый фильтр при торможении (target → 0)
        moving_toward_zero = abs(target) < abs(self.x)
        alpha = self.alpha_brake if moving_toward_zero else self.alpha_accel
        self.x = (1.0 - alpha) * self.x + alpha * float(target)
        # Сбрасываем в ноль если совсем близко (убираем ползучесть)
        if abs(self.x) < 0.005:
            self.x = 0.0
        return self.x


def _read_key(timeout=LOOP_DT):
    """Читает одну клавишу без блокировки. Возвращает '' при таймауте."""
    if os.name == 'nt':
        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                return ch.decode('utf-8', errors='ignore')
            time.sleep(0.005)
        return ''
    # POSIX
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if rlist else ''


def _init_camera():
    """Инициализирует PWM-серво камеры. Возвращает (pan, tilt) или None."""
    try:
        from jetauto_sdk.pwm_servo import PWMServo
        pan  = PWMServo(1)
        tilt = PWMServo(2)
        pan.start()
        tilt.start()
        time.sleep(0.3)
        pan.set_position(PAN_CENTER,  500)
        tilt.set_position(TILT_CENTER, 500)
        time.sleep(0.3)
        rospy.loginfo('teleop: камера OK')
        return pan, tilt
    except Exception as e:
        rospy.logwarn('teleop: камера недоступна — %s', e)
        return None, None


def main():
    if os.name != 'nt':
        import tty
        import termios
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())

    rospy.init_node('jetauto_teleop', anonymous=True)
    pub = rospy.Publisher('/jetauto_controller/cmd_vel', Twist, queue_size=1)

    pan_servo, tilt_servo = _init_camera()
    camera_ok = pan_servo is not None
    pan_pos   = PAN_CENTER
    tilt_pos  = TILT_CENTER

    # Отдельные фильтры для каждой оси — независимая настройка
    fx  = FirstOrderFilter()   # linear.x  (вперёд/назад)
    fy  = FirstOrderFilter()   # linear.y  (стрейф)
    faz = FirstOrderFilter()   # angular.z (поворот)

    target_x  = 0.0
    target_y  = 0.0
    target_az = 0.0

    print(BANNER)
    if not camera_ok:
        print('  [!] Камера недоступна, управление движением работает.')
    print()

    try:
        while not rospy.is_shutdown():
            key = _read_key().lower()

            # ── Движение ──────────────────────────────────────────
            if key == 'w':
                target_x = LIN_VEL;  target_y = 0.0;    target_az = 0.0
            elif key == 's':
                target_x = -LIN_VEL; target_y = 0.0;    target_az = 0.0
            elif key == 'a':
                target_az =  ANG_VEL; target_x = 0.0;   target_y = 0.0
            elif key == 'd':
                target_az = -ANG_VEL; target_x = 0.0;   target_y = 0.0
            elif key == 'q':
                target_y =  LIN_VEL;  target_x = 0.0;   target_az = 0.0
            elif key == 'e':
                target_y = -LIN_VEL;  target_x = 0.0;   target_az = 0.0
            elif key == '':
                # Таймаут — нет нажатия, плавная остановка
                target_x = 0.0;  target_y = 0.0;  target_az = 0.0

            # ── Камера ────────────────────────────────────────────
            elif key == 'j' and camera_ok:
                pan_pos = max(PAN_MIN, pan_pos - CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
            elif key == 'l' and camera_ok:
                pan_pos = min(PAN_MAX, pan_pos + CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
            elif key == 'i' and camera_ok:
                tilt_pos = max(TILT_MIN, tilt_pos - CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
            elif key == 'k' and camera_ok:
                tilt_pos = min(TILT_MAX, tilt_pos + CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
            elif key == '0' and camera_ok:
                pan_pos  = PAN_CENTER
                tilt_pos = TILT_CENTER
                pan_servo.set_position(pan_pos,  500)
                tilt_servo.set_position(tilt_pos, 500)

            elif key == '\x03':   # Ctrl-C
                break

            # ── Применяем фильтры и публикуем ────────────────────
            twist = Twist()
            twist.linear.x  = fx.update(target_x)
            twist.linear.y  = fy.update(target_y)
            twist.angular.z = faz.update(target_az)
            pub.publish(twist)

    except Exception as e:
        rospy.logerr('teleop: %s', e)

    finally:
        pub.publish(Twist())
        if camera_ok:
            pan_servo.set_position(PAN_CENTER,  500)
            tilt_servo.set_position(TILT_CENTER, 500)
        if os.name != 'nt':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        rospy.loginfo('teleop: завершён')


if __name__ == '__main__':
    main()
