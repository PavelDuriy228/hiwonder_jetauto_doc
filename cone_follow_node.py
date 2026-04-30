#!/usr/bin/env python3
# encoding: utf-8
# Следование за красным конусом.
# Улучшения vs оригинал:
#   - PIDController с anti-windup и I-членом (вместо P-only из jetauto_sdk)
#   - FirstOrderFilter на линейной скорости (нет рывков)
#   - Поворот корпуса через angular.z (раньше следила только камера)
#   - Скорость пропорциональна расстоянию до конуса
#   - State machine: LOST → TRACKING → NEAR

import cv2
import yaml
import rospy
import signal
import numpy as np
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist
from jetauto_sdk.pwm_servo import PWMServo

LAB_CONFIG = '/home/jetauto/jetauto_software/lab_tool/lab_config.yaml'

MIN_AREA     = 1500   # px² — минимальная площадь контура
STOP_AREA    = 35000  # px² — конус близко, стоп
FRAME_W      = 640
FRAME_H      = 480
FRAME_CX     = FRAME_W // 2
FRAME_CY     = FRAME_H // 2

PAN_CENTER   = 1500
TILT_CENTER  = 1500
PAN_MIN,  PAN_MAX  = 800, 2200
TILT_MIN, TILT_MAX = 800, 2200
PAN_SIGN     = 1
TILT_SIGN    = 1

RATE_HZ      = 20
DT           = 1.0 / RATE_HZ

# Состояния state machine
LOST     = 'lost'
TRACKING = 'tracking'
NEAR     = 'near'


class PIDController:
    """PID с anti-windup: интегратор замораживается при насыщении выхода.

    Источник идеи: openpilot/common/pid.py
    """

    def __init__(self, kp, ki, kd, pos_limit, neg_limit):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.pos_limit = pos_limit
        self.neg_limit = neg_limit
        self.i = 0.0
        self.last_error = 0.0

    def reset(self):
        self.i = 0.0
        self.last_error = 0.0

    def update(self, error, feedforward=0.0, freeze_integrator=False):
        """Возвращает управляющий сигнал, ограниченный [neg_limit, pos_limit]."""
        p = self.kp * error
        d = self.kd * (error - self.last_error) / DT
        self.last_error = error

        if not freeze_integrator:
            new_i = self.i + self.ki * DT * error
            # Anti-windup: не растёт если выход уже насыщен
            if self.neg_limit < p + new_i + d + feedforward < self.pos_limit:
                self.i = new_i

        output = p + self.i + d + feedforward
        return max(self.neg_limit, min(self.pos_limit, output))


class FirstOrderFilter:
    """LP-фильтр первого порядка: x = (1-a)*x + a*input.

    Источник идеи: openpilot/common/filter_simple.py
    rc — постоянная времени в секундах (больше = медленнее реакция).
    """

    def __init__(self, x0, rc):
        self.alpha = DT / (rc + DT)
        self.x = float(x0)

    def update(self, value):
        self.x = (1.0 - self.alpha) * self.x + self.alpha * float(value)
        return self.x


class ConeFollowNode:
    def __init__(self, name):
        rospy.init_node(name, anonymous=True)
        self.running = True
        self.image = None
        self.state = LOST

        signal.signal(signal.SIGINT, self.shutdown)

        with open(LAB_CONFIG, 'r') as f:
            lab_data = yaml.safe_load(f)
        color_range = lab_data['lab']['Stereo']['red']
        self.lab_min = tuple(color_range['min'])
        self.lab_max = tuple(color_range['max'])

        # PID камеры — servo units/tick
        self.pid_pan  = PIDController(kp=0.40, ki=0.008, kd=0.015,
                                      pos_limit=200, neg_limit=-200)
        self.pid_tilt = PIDController(kp=0.40, ki=0.008, kd=0.015,
                                      pos_limit=200, neg_limit=-200)

        # PID поворота корпуса — rad/s по ошибке в пикселях
        self.pid_steer = PIDController(kp=0.003, ki=0.00008, kd=0.001,
                                       pos_limit=0.5, neg_limit=-0.5)

        # Фильтр линейной скорости: rc=0.25 с — плавный разгон и торможение
        self.lin_filter = FirstOrderFilter(x0=0.0, rc=0.25)

        self.pan_pos  = PAN_CENTER
        self.tilt_pos = TILT_CENTER
        self.pan_servo  = PWMServo(1)
        self.tilt_servo = PWMServo(2)
        self.pan_servo.start()
        self.tilt_servo.start()
        self.pan_servo.set_position(self.pan_pos,  500)
        self.tilt_servo.set_position(self.tilt_pos, 500)

        self.mecanum_pub = rospy.Publisher(
            '/jetauto_controller/cmd_vel', Twist, queue_size=1)

        camera = rospy.get_param('/depth_camera/camera_name', 'camera')
        rospy.Subscriber('/%s/rgb/image_raw' % camera,
                         Image, self.image_callback, queue_size=1)

        rospy.loginfo('cone_follow: waiting for camera...')
        while self.image is None and not rospy.is_shutdown():
            rospy.sleep(0.1)
        rospy.loginfo('cone_follow: started')

        self.mecanum_pub.publish(Twist())
        self.follow_loop()

    def image_callback(self, ros_image):
        self.image = np.ndarray(
            shape=(ros_image.height, ros_image.width, 3),
            dtype=np.uint8,
            buffer=ros_image.data)

    def detect_cone(self, img):
        """Возвращает (cx, cy, area) наибольшего красного контура или None."""
        img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        mask = cv2.inRange(img_lab,
                           np.array(self.lab_min, dtype=np.uint8),
                           np.array(self.lab_max, dtype=np.uint8))
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < MIN_AREA:
            return None

        x, y, w, h = cv2.boundingRect(largest)
        return x + w // 2, y + h // 2, area

    def follow_loop(self):
        rate = rospy.Rate(RATE_HZ)
        while self.running and not rospy.is_shutdown():
            twist = Twist()

            if self.image is not None:
                result = self.detect_cone(self.image.copy())

                if result is None:
                    self.state = LOST
                    self.pid_steer.reset()
                elif result[2] >= STOP_AREA:
                    self.state = NEAR
                    self.pid_steer.reset()
                else:
                    self.state = TRACKING

                if self.state == TRACKING:
                    cx, cy, area = result

                    # Скорость пропорциональна расстоянию: дальше — быстрее
                    target_lin = max(0.05, 0.15 * (1.0 - area / STOP_AREA))

                    # Ошибки по осям кадра
                    pan_error  = cx - FRAME_CX   # >0 = конус правее центра
                    tilt_error = cy - FRAME_CY   # >0 = конус ниже центра

                    # Поворот корпуса: если конус правее — повернуть вправо
                    # (angular.z > 0 = CCW = влево, поэтому знак минус)
                    at_pan_limit = (self.pan_pos <= PAN_MIN or
                                    self.pan_pos >= PAN_MAX)
                    twist.angular.z = -self.pid_steer.update(
                        pan_error, freeze_integrator=at_pan_limit)

                    # Серво камеры — быстрая локальная коррекция
                    if abs(pan_error) > 15:
                        delta_pan = self.pid_pan.update(
                            pan_error,
                            freeze_integrator=at_pan_limit)
                        self.pan_pos = int(self.pan_pos + PAN_SIGN * delta_pan)
                        self.pan_pos = max(PAN_MIN, min(PAN_MAX, self.pan_pos))
                        self.pan_servo.set_position(self.pan_pos, 20)

                    if abs(tilt_error) > 15:
                        delta_tilt = self.pid_tilt.update(tilt_error)
                        self.tilt_pos = int(
                            self.tilt_pos - TILT_SIGN * delta_tilt)
                        self.tilt_pos = max(TILT_MIN, min(TILT_MAX, self.tilt_pos))
                        self.tilt_servo.set_position(self.tilt_pos, 20)

                    rospy.loginfo_throttle(0.5,
                        'cone [%s] cx=%d area=%.0f lin=%.2f ang=%.2f' % (
                            self.state, cx, area,
                            target_lin, twist.angular.z))
                else:
                    target_lin = 0.0
                    rospy.loginfo_throttle(1.0, 'cone [%s]' % self.state)
            else:
                target_lin = 0.0

            twist.linear.x = self.lin_filter.update(target_lin)
            self.mecanum_pub.publish(twist)
            rate.sleep()

    def shutdown(self, signum, frame):
        self.running = False
        self.mecanum_pub.publish(Twist())
        self.pan_servo.set_position(PAN_CENTER,  500)
        self.tilt_servo.set_position(TILT_CENTER, 500)
        rospy.loginfo('cone_follow: shutdown')


if __name__ == '__main__':
    ConeFollowNode('cone_follow')
