#!/usr/bin/env python3
# encoding: utf-8
# Следование за красным конусом по цвету (chassis only, no arm)

import rospy
import signal
import jetauto_sdk.pid as pid
from geometry_msgs.msg import Twist
from jetauto_interfaces.msg import ColorsInfo, ColorDetect
from jetauto_interfaces.srv import SetColorDetectParam

# Минимальная площадь bbox чтобы считать конус найденным
MIN_AREA = 800
# Площадь при которой останавливаемся (конус близко)
STOP_AREA = 40000

class ConeFollowNode:
    def __init__(self, name):
        rospy.init_node(name, anonymous=True)
        self.name = name
        self.running = True
        self.center = None

        signal.signal(signal.SIGINT, self.shutdown)

        # PID для поворота: держим конус по центру кадра по оси X
        self.pid_steer = pid.PID(0.003, 0.0, 0.0)

        self.mecanum_pub = rospy.Publisher('/jetauto_controller/cmd_vel', Twist, queue_size=1)
        rospy.Subscriber('/color_detect/color_info', ColorsInfo, self.color_callback)

        # Ждём пока color_detect поднимется
        rospy.wait_for_service('/color_detect/set_param')
        self.set_color('red')

        rospy.loginfo('cone_follow: started, tracking red')
        self.mecanum_pub.publish(Twist())
        self.follow_loop()

    def set_color(self, color):
        msg = ColorDetect()
        msg.color_name = color
        msg.detect_type = 'rect'   # конус — прямоугольник, не круг
        try:
            srv = rospy.ServiceProxy('/color_detect/set_param', SetColorDetectParam)
            srv([msg])
        except rospy.ServiceException as e:
            rospy.logerr('set_param failed: %s' % e)

    def color_callback(self, msg):
        if msg.data:
            c = msg.data[0]
            area = c.width * c.height
            if area > MIN_AREA:
                self.center = c
            else:
                self.center = None
        else:
            self.center = None

    def follow_loop(self):
        rate = rospy.Rate(20)
        while self.running and not rospy.is_shutdown():
            twist = Twist()
            if self.center is not None:
                area = self.center.width * self.center.height
                frame_w = self.center.width  # ширина кадра хранится в ColorInfo.width — нет,
                # width/height это размер bbox. Ширину кадра берём как параметр (640px)
                frame_center_x = 320

                if area >= STOP_AREA:
                    # Конус близко — стоим
                    rospy.loginfo_throttle(1, 'cone close, stopping')
                else:
                    # Едем вперёд
                    twist.linear.x = 0.12

                    # Поворот: отклонение центра bbox от центра кадра
                    error = self.center.x - frame_center_x
                    if abs(error) > 15:
                        self.pid_steer.SetPoint = 0
                        self.pid_steer.update(error)
                        angular = -self.pid_steer.output
                        angular = max(-0.4, min(0.4, angular))
                        twist.angular.z = angular

            self.mecanum_pub.publish(twist)
            rate.sleep()

    def shutdown(self, signum, frame):
        self.running = False
        self.mecanum_pub.publish(Twist())
        rospy.loginfo('cone_follow: shutdown')

if __name__ == '__main__':
    ConeFollowNode('cone_follow')
