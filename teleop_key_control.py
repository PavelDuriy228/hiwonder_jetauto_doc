#!/usr/bin/env python3
# encoding: utf-8
import rospy
from geometry_msgs.msg import Twist
from jetauto_sdk.pwm_servo import PWMServo

import sys, select, os
if os.name == 'nt':
    import msvcrt, time
else:
    import tty, termios

LIN_VEL  = 0.2    # м/с
ANG_VEL  = 0.5    # рад/с
CAM_STEP = 100    # единиц серво за одно нажатие

PAN_CENTER  = 1500
TILT_CENTER = 1500
PAN_MIN,  PAN_MAX  = 800, 2200
TILT_MIN, TILT_MAX = 800, 2200

msg = """
╔══════════════════════════════════╗
║     Управление JetAuto           ║
╠══════════════════════════════════╣
║  Движение:       Камера:         ║
║      W               I           ║
║   A  S  D         J  K  L        ║
║                                  ║
║  W/S  — вперёд / назад           ║
║  A/D  — поворот влево / вправо   ║
║                                  ║
║  I/K  — камера вверх / вниз      ║
║  J/L  — камера влево / вправо    ║
║  0    — камера в центр           ║
║                                  ║
║  Ctrl-C — выход                  ║
╚══════════════════════════════════╝
"""


def getKey():
    if os.name == 'nt':
        startTime = time.time()
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                return ch.decode() if sys.version_info[0] >= 3 else ch
            elif time.time() - startTime > 0.1:
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

    pan_servo  = PWMServo(1)   # pan  — GPIO 13
    tilt_servo = PWMServo(2)   # tilt — GPIO 12
    pan_servo.start()
    tilt_servo.start()
    pan_pos  = PAN_CENTER
    tilt_pos = TILT_CENTER
    pan_servo.set_position(pan_pos,  500)
    tilt_servo.set_position(tilt_pos, 500)

    lin_vel = 0.0
    ang_vel = 0.0
    last_lin = 0.0
    last_ang = 0.0

    try:
        print(msg)
        while not rospy.is_shutdown():
            key = getKey().lower()

            if key == '':
                # Таймаут — сбрасываем вращение, линейная скорость сохраняется
                ang_vel = 0.0

            elif key == 'w':
                lin_vel =  LIN_VEL
            elif key == 's':
                lin_vel = -LIN_VEL
            elif key == 'a':
                ang_vel =  ANG_VEL
                lin_vel =  0.0
            elif key == 'd':
                ang_vel = -ANG_VEL
                lin_vel =  0.0

            elif key == 'j':
                pan_pos = max(PAN_MIN, pan_pos - CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
                print('pan  %d' % pan_pos)
            elif key == 'l':
                pan_pos = min(PAN_MAX, pan_pos + CAM_STEP)
                pan_servo.set_position(pan_pos, 200)
                print('pan  %d' % pan_pos)
            elif key == 'i':
                tilt_pos = max(TILT_MIN, tilt_pos - CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
                print('tilt %d' % tilt_pos)
            elif key == 'k':
                tilt_pos = min(TILT_MAX, tilt_pos + CAM_STEP)
                tilt_servo.set_position(tilt_pos, 200)
                print('tilt %d' % tilt_pos)
            elif key == '0':
                pan_pos  = PAN_CENTER
                tilt_pos = TILT_CENTER
                pan_servo.set_position(pan_pos,  500)
                tilt_servo.set_position(tilt_pos, 500)
                print('camera centered')

            elif key == '\x03':
                break

            twist = Twist()
            twist.linear.x  = lin_vel
            twist.angular.z = ang_vel

            if last_lin != lin_vel or last_ang != ang_vel:
                mecanum_pub.publish(twist)
            last_lin = lin_vel
            last_ang = ang_vel

    except Exception as e:
        print(e)

    finally:
        mecanum_pub.publish(Twist())
        pan_servo.set_position(PAN_CENTER,  500)
        tilt_servo.set_position(TILT_CENTER, 500)
        if os.name != 'nt':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
