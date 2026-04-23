#!/usr/bin/env python3
# encoding: utf-8
# Следование за красным конусом — прямая обработка изображения с камеры

import cv2
import yaml
import rospy
import signal
import numpy as np
import jetauto_sdk.pid as pid
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist

LAB_CONFIG = '/home/jetauto/jetauto_software/lab_tool/lab_config.yaml'

# Минимальная площадь контура чтобы считать конус найденным (px²)
MIN_AREA = 1500
# Площадь при которой останавливаемся — конус близко
STOP_AREA = 35000
# Ширина и центр кадра
FRAME_W = 640
FRAME_CENTER_X = FRAME_W // 2


class ConeFollowNode:
    def __init__(self, name):
        rospy.init_node(name, anonymous=True)
        self.running = True
        self.image = None

        signal.signal(signal.SIGINT, self.shutdown)

        # Загружаем LAB-диапазон для красного из калибровки камеры
        with open(LAB_CONFIG, 'r') as f:
            lab_data = yaml.safe_load(f)
        color_range = lab_data['lab']['Stereo']['red']
        self.lab_min = tuple(color_range['min'])
        self.lab_max = tuple(color_range['max'])

        self.pid_steer = pid.PID(0.003, 0.0, 0.0)
        self.mecanum_pub = rospy.Publisher('/jetauto_controller/cmd_vel', Twist, queue_size=1)

        camera = rospy.get_param('/depth_camera/camera_name', 'camera')
        rospy.Subscriber('/%s/rgb/image_raw' % camera, Image, self.image_callback, queue_size=1)

        rospy.loginfo('cone_follow: waiting for camera...')
        while self.image is None and not rospy.is_shutdown():
            rospy.sleep(0.1)
        rospy.loginfo('cone_follow: started, tracking red')

        self.mecanum_pub.publish(Twist())
        self.follow_loop()

    def image_callback(self, ros_image):
        self.image = np.ndarray(
            shape=(ros_image.height, ros_image.width, 3),
            dtype=np.uint8,
            buffer=ros_image.data
        )

    def detect_cone(self, img):
        """Возвращает (cx, area) наибольшего красного контура или None."""
        img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        mask = cv2.inRange(img_lab,
                           np.array(self.lab_min, dtype=np.uint8),
                           np.array(self.lab_max, dtype=np.uint8))
        # Убираем шум
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < MIN_AREA:
            return None

        x, y, w, h = cv2.boundingRect(largest)
        cx = x + w // 2
        return cx, area

    def follow_loop(self):
        rate = rospy.Rate(20)
        while self.running and not rospy.is_shutdown():
            twist = Twist()
            if self.image is not None:
                result = self.detect_cone(self.image.copy())
                if result is not None:
                    cx, area = result
                    if area >= STOP_AREA:
                        rospy.loginfo_throttle(1, 'cone close (area=%.0f), stopping' % area)
                    else:
                        twist.linear.x = 0.12

                        error = cx - FRAME_CENTER_X
                        if abs(error) > 15:
                            self.pid_steer.SetPoint = 0
                            self.pid_steer.update(error)
                            angular = -self.pid_steer.output
                            twist.angular.z = max(-0.4, min(0.4, angular))

                        rospy.loginfo_throttle(0.5, 'cone cx=%d area=%.0f angular=%.3f' % (cx, area, twist.angular.z))

            self.mecanum_pub.publish(twist)
            rate.sleep()

    def shutdown(self, signum, frame):
        self.running = False
        self.mecanum_pub.publish(Twist())
        rospy.loginfo('cone_follow: shutdown')


if __name__ == '__main__':
    ConeFollowNode('cone_follow')
