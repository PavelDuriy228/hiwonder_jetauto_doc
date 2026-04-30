#!/usr/bin/env python3
# encoding: utf-8
import sys, os, select, time
import rospy
from geometry_msgs.msg import Twist

if os.name == 'nt':
    import msvcrt
else:
    import tty, termios

# ── Скорости ──────────────────────────────────────────────
LIN_VEL  = 0.20   # м/с   макс. линейная (вперёд/стрейф)
ANG_VEL  = 0.60   # рад/с макс. угловая
LIN_RATE = 0.40   # м/с²  разгон/торможение линейной
ANG_RATE = 1.20   # рад/с² разгон/торможение угловой

# ── Камера ────────────────────────────────────────────────
CAM_STEP    = 100
PAN_CENTER  = 1500
TILT_CENTER = 1500
PAN_MIN,  PAN_MAX  = 800, 2200
TILT_MIN, TILT_MAX = 800, 2200

msg = """
╔═══════════════════════════════════════╗
║        Управление JetAuto             ║
╠═══════════════════════════════════════╣
║  Движение:          Камера:           ║
║        W                 I            ║
║   Q  A  D  E         J   K   L        ║
║        S             0 — в центр      ║
║                                       ║
║  W / S  — вперёд / назад              ║
║  A / D  — поворот влево / вправо      ║
║  Q / E  — стрейф влево / вправо       ║
║  Скорость нарастает плавно.           ║
║  Противоположная клавиша — сначала    ║
║  тормозит, затем разгоняет обратно.   ║
║                                       ║
║  I / K  — камера вверх / вниз         ║
║  J / L  — камера влево / вправо       ║
║  0      — камера в центр              ║
║                                       ║
║  Ctrl-C — выход                       ║
╚═══════════════════════════════════════╝
"""


def make_profile(cur, target, rate, dt):
    """Плавно сдвигает cur к target со скоростью rate (ед/с)."""
    step = rate * dt
    if cur < target:
        return min(target, cur + step)
    elif cur > target:
        return max(target, cur - step)
    return target


def get_key():
    if os.name == 'nt':
        start = time.time()
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                return ch.decode() if sys.version_info[0] >= 3 else ch
            elif time.time() - start > 0.1:
                return ''
    tty.setraw(sys.stdin.fileno())
    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
    key = sys.stdin.read(1) if rlist else ''
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
    return key


if __name__ == '__main__':
    if os.name != 'nt':
        settings = termios.tcgetattr(sys.stdin)

    rospy.init_node('jetauto_teleop')
    mecanum_pub = rospy.Publisher('jetauto_controller/cmd_vel', Twist, queue_size=10)

    # ── Инициализация камеры ──────────────────────────────
    camera_ok = False
    pan_pos   = PAN_CENTER
    tilt_pos  = TILT_CENTER
    try:
        from jetauto_sdk.pwm_servo import PWMServo
        pan_servo  = PWMServo(1)   # pan  — GPIO 13
        tilt_servo = PWMServo(2)   # tilt — GPIO 12
        pan_servo.start()
        tilt_servo.start()
        time.sleep(0.5)            # ждём инициализацию GPIO PWM
        pan_servo.set_position(PAN_CENTER,  500)
        tilt_servo.set_position(TILT_CENTER, 500)
        time.sleep(0.5)
        camera_ok = True
        print('Камера: OK (pan=%d tilt=%d)' % (pan_pos, tilt_pos))
    except Exception as cam_err:
        print('Камера: ОШИБКА — %s' % cam_err)
        print('Управление движением всё равно работает.')

    # ── Состояние движения ────────────────────────────────
    target_x   = 0.0
    target_y   = 0.0
    target_ang = 0.0
    cur_x      = 0.0
    cur_y      = 0.0
    cur_ang    = 0.0
    last_time  = time.time()

    try:
        print(msg)
        while not rospy.is_shutdown():
            key = get_key().lower()
            now = time.time()
            dt  = now - last_time
            last_time = now

            # ── Движение ──────────────────────────────────
            if key == 'w':
                target_x = LIN_VEL;  target_y = 0.0;  target_ang = 0.0
            elif key == 's':
                target_x = -LIN_VEL; target_y = 0.0;  target_ang = 0.0
            elif key == 'a':
                target_ang =  ANG_VEL; target_x = 0.0; target_y = 0.0
            elif key == 'd':
                target_ang = -ANG_VEL; target_x = 0.0; target_y = 0.0
            elif key == 'q':
                target_y =  LIN_VEL;  target_x = 0.0; target_ang = 0.0
            elif key == 'e':
                target_y = -LIN_VEL;  target_x = 0.0; target_ang = 0.0
            elif key == '':
                # Нет нажатия — плавная остановка
                target_x = 0.0; target_y = 0.0; target_ang = 0.0

            # ── Камера ────────────────────────────────────
            elif key == 'j' and camera_ok:
                pan_pos = max(PAN_MIN, pan_pos - CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
                print('pan  %d' % pan_pos)
            elif key == 'l' and camera_ok:
                pan_pos = min(PAN_MAX, pan_pos + CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
                print('pan  %d' % pan_pos)
            elif key == 'i' and camera_ok:
                tilt_pos = max(TILT_MIN, tilt_pos - CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
                print('tilt %d' % tilt_pos)
            elif key == 'k' and camera_ok:
                tilt_pos = min(TILT_MAX, tilt_pos + CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
                print('tilt %d' % tilt_pos)
            elif key == '0' and camera_ok:
                pan_pos  = PAN_CENTER
                tilt_pos = TILT_CENTER
                pan_servo.set_position(pan_pos,  500)
                tilt_servo.set_position(tilt_pos, 500)
                print('camera centered')

            elif key == '\x03':
                break

            # ── Плавное изменение скоростей ───────────────
            cur_x   = make_profile(cur_x,   target_x,   LIN_RATE, dt)
            cur_y   = make_profile(cur_y,   target_y,   LIN_RATE, dt)
            cur_ang = make_profile(cur_ang, target_ang, ANG_RATE, dt)

            twist = Twist()
            twist.linear.x  = cur_x
            twist.linear.y  = cur_y
            twist.angular.z = cur_ang
            mecanum_pub.publish(twist)

    except Exception as ex:
        print(ex)

    finally:
        mecanum_pub.publish(Twist())
        if camera_ok:
            pan_servo.set_position(PAN_CENTER,  500)
            tilt_servo.set_position(TILT_CENTER, 500)
        if os.name != 'nt':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
