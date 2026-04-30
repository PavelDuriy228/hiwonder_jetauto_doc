#!/usr/bin/env python3
# encoding: utf-8
# @data:2022/11/07
# @author:aiden
# 物体跟踪
import cv2
import rospy
import numpy as np
import jetauto_sdk.pid as pid
import jetauto_sdk.fps as fps
import jetauto_sdk.pwm_servo as pwm_servo_mod
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist

PAN_CENTER  = 1500
TILT_CENTER = 1500
PAN_MIN,  PAN_MAX  = 800, 2200
TILT_MIN, TILT_MAX = 800, 2200
PAN_SIGN  = 1   # set to -1 if pan direction is reversed
TILT_SIGN = 1   # set to -1 if tilt direction is reversed

class KCFNode:
    def __init__(self, name):
        rospy.init_node(name)
        self.name = name
        self.pid_d = pid.PID(0.8, 0, 0)
        #self.pid_d = pid.PID(0, 0, 0)

        self.pid_pan  = pid.PID(0.5, 0, 0)
        self.pid_tilt = pid.PID(0.5, 0, 0)
        self.go_speed = 0.007
        self.linear_x = 0
        self.pan_pos  = PAN_CENTER
        self.tilt_pos = TILT_CENTER
        self.pan_servo  = pwm_servo_mod.PWMServo(1)
        self.tilt_servo = pwm_servo_mod.PWMServo(2)
        self.pan_servo.start()
        self.tilt_servo.start()
        self.pan_servo.set_position(self.pan_pos,  500)
        self.tilt_servo.set_position(self.tilt_pos, 500)

        self.fps = fps.FPS()
        
        self.DISTANCE = 100 # 停止距离单位cm
        self.distance = self.DISTANCE # 选取时停止距离单位cm
        self.mouse_click = False
        self.selection = None   # 实时跟踪鼠标的跟踪区域
        self.track_window = None   # 要检测的物体所在区域
        self.drag_start = None   # 标记，是否开始拖动鼠标
        self.start_circle = True
        self.start_click = False
        self.depth_frame = None

        self.tracker = cv2.legacy.TrackerMedianFlow_create()
        fs = cv2.FileStorage("custom_csrt.xml", cv2.FILE_STORAGE_READ)
        fn = fs.getFirstTopLevelNode()
        #self.tracker.save('default_csrt.xml')
        self.tracker.read(fn)

        cv2.namedWindow(name, 1)
        cv2.setMouseCallback(name, self.onmouse)
        camera = rospy.get_param('/depth_camera/camera_name', 'camera')
        self.image_sub = rospy.Subscriber('/%s/rgb/image_raw'%camera, Image, self.image_callback, queue_size=1)  # 订阅目标检测节点
        self.depth_image_sub = rospy.Subscriber('/%s/depth/image_raw'%camera, Image, self.depth_image_callback, queue_size=1)
        self.mecanum_pub = rospy.Publisher('/jetauto_controller/cmd_vel', Twist, queue_size=1)
        rospy.sleep(0.2)
        self.mecanum_pub.publish(Twist())

    def depth_image_callback(self, depth_image):
        self.depth_frame = np.ndarray(shape=(depth_image.height, depth_image.width), dtype=np.uint16, buffer=depth_image.data)
        
    def image_callback(self, ros_image: Image):
        rgb_image = np.ndarray(shape=(ros_image.height, ros_image.width, 3), dtype=np.uint8, buffer=ros_image.data)  # 将自定义图像消息转化为图像
        
        try:
            result_image = self.image_proc(np.copy(rgb_image))
        except BaseException as e:
            print(e)
            result_image = rgb_image
        cv2.imshow(self.name, cv2.cvtColor(result_image, cv2.COLOR_RGB2BGR))
        key = cv2.waitKey(1)
        if key != -1:
            self.mecanum_pub.publish(Twist())
            self.pan_servo.set_position(PAN_CENTER,  500)
            self.tilt_servo.set_position(TILT_CENTER, 500)
            rospy.signal_shutdown('shutdown')
     
    #鼠标点击事件回调函数
    def onmouse(self, event, x, y, flags, param):   
        if event == cv2.EVENT_LBUTTONDOWN:       #鼠标左键按下
            self.mouse_click = True
            self.drag_start = (x, y)       #鼠标起始位置
            self.track_window = None
        if self.drag_start:       #是否开始拖动鼠标，记录鼠标位置
            xmin = min(x, self.drag_start[0])
            ymin = min(y, self.drag_start[1])
            xmax = max(x, self.drag_start[0])
            ymax = max(y, self.drag_start[1])
            self.selection = (xmin, ymin, xmax, ymax)
        if event == cv2.EVENT_LBUTTONUP:        #鼠标左键松开
            self.mouse_click = False
            self.drag_start = None
            self.track_window = self.selection
            self.selection = None
            roi = self.depth_frame[self.track_window[1]:self.track_window[3], self.track_window[0]:self.track_window[2]]
            try:
                roi_h, roi_w = roi.shape
                if roi_h > 0 and roi_w > 0:
                    roi_cut = [1/3, 1/3]
                    if roi_w < 100:
                        roi_cut[1] = 0
                    if roi_h < 100:
                        roi_cut[0] = 0
                    roi_distance = roi[int(roi_h*roi_cut[0]):(roi_h - int(roi_h*roi_cut[0])), 
                            int(roi_w*roi_cut[1]):(roi_w - int(roi_w*roi_cut[1]))]
                    self.distance = int(np.mean(roi_distance[np.logical_and(roi_distance>0, roi_distance<30000)])/10)
                else:
                    self.distance = self.DISTANCE
            except:
                self.distance = self.DISTANCE
        if event == cv2.EVENT_RBUTTONDOWN:
            self.mouse_click = False
            self.selection = None   # 实时跟踪鼠标的跟踪区域
            self.track_window = None   # 要检测的物体所在区域
            self.drag_start = None   # 标记，是否开始拖动鼠标
            self.start_circle = True
            self.start_click = False
            self.mecanum_pub.publish(Twist())
            self.tracker = cv2.legacy.TrackerMedianFlow_create()
            fs = cv2.FileStorage("custom_csrt.xml", cv2.FILE_STORAGE_READ)
            fn = fs.getFirstTopLevelNode()
            #tracker.save('default_csrt.xml')
            self.tracker.read(fn)

    def image_proc(self, image):
        if self.start_circle:
            # 用鼠标拖拽一个框来指定区域             
            if self.track_window:      #跟踪目标的窗口画出后，实时标出跟踪目标
                cv2.rectangle(image, (self.track_window[0], self.track_window[1]), (self.track_window[2], self.track_window[3]), (0, 0, 255), 2)
            elif self.selection:      #跟踪目标的窗口随鼠标拖动实时显示
                cv2.rectangle(image, (self.selection[0], self.selection[1]), (self.selection[2], self.selection[3]), (0, 0, 255), 2)
            if self.mouse_click:
                self.start_click = True
            if self.start_click:
                if not self.mouse_click:
                    self.start_circle = False
            if not self.start_circle:
                print('start tracking')
                bbox = (self.track_window[0], self.track_window[1], self.track_window[2] - self.track_window[0], self.track_window[3] - self.track_window[1])
                self.tracker.init(image, bbox)
        else:
            twist = Twist()
            ok, bbox = self.tracker.update(image)
            if ok and min(bbox) > 0:
                p1 = (int(bbox[0]), int(bbox[1]))
                p2 = (int(bbox[0] + bbox[2]), int(bbox[1] + bbox[3]))
                center = [(p1[0] + p2[0])/2, (p1[1] + p2[1])/2]
                roi = self.depth_frame[p1[1]:p2[1], p1[0]:p2[0]]
                roi_h, roi_w = roi.shape
                if roi_h > 0 and roi_w > 0:
                    roi_cut = [1/3, 1/3]
                    if roi_w < 100:
                        roi_cut[1] = 0
                    if roi_h < 100:
                        roi_cut[0] = 0
                    roi_distance = roi[int(roi_h*roi_cut[0]):(roi_h - int(roi_h*roi_cut[0])), 
                            int(roi_w*roi_cut[1]):(roi_w - int(roi_w*roi_cut[1]))]
                    try:
                        distance = int(np.mean(roi_distance[np.logical_and(roi_distance>0, roi_distance<30000)])/10)
                    except:
                        distance = self.DISTANCE
                    cv2.putText(image, 'Distance: ' + str(distance) + 'cm', (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1) 
                    #cv2.drawMarker(image, (int(center[0]), int(center[1])), (0, 255, 0), markerType=0, thickness=2, line_type=cv2.LINE_AA)
                    cv2.rectangle(image, p1, p2, (0, 255, 0), 2, 1)
                    h, w = image.shape[:2]
                    
                    self.pid_d.SetPoint = self.distance
                    if abs(distance - self.distance) < 10:
                        distance = self.distance
                    self.pid_d.update(distance)  #更新pid
                    tmp = self.go_speed - self.pid_d.output
                    self.linear_x = tmp
                    if tmp > 0.15:
                        self.linear_x = 0.15
                    if tmp < -0.15:
                        self.linear_x = -0.15
                    if abs(tmp) < 0.008:
                        self.linear_x = 0
                    twist.linear.x = self.linear_x
                    
                    # Pan — горизонтальное слежение камерой
                    self.pid_pan.SetPoint = w / 2
                    if abs(center[0] - w / 2) < 10:
                        center[0] = w / 2
                    self.pid_pan.update(center[0])
                    self.pan_pos = int(self.pan_pos + PAN_SIGN * self.pid_pan.output)
                    self.pan_pos = max(PAN_MIN, min(PAN_MAX, self.pan_pos))
                    self.pan_servo.set_position(self.pan_pos, 20)

                    # Tilt — вертикальное слежение камерой
                    self.pid_tilt.SetPoint = h / 2
                    if abs(center[1] - h / 2) < 10:
                        center[1] = h / 2
                    self.pid_tilt.update(center[1])
                    self.tilt_pos = int(self.tilt_pos - TILT_SIGN * self.pid_tilt.output)
                    self.tilt_pos = max(TILT_MIN, min(TILT_MAX, self.tilt_pos))
                    self.tilt_servo.set_position(self.tilt_pos, 20)
                else:
                    cv2.putText(image, "Tracking failure detected !", (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
            else:
                # Tracking failure
                cv2.putText(image, "Tracking failure detected !", (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
            self.mecanum_pub.publish(twist)
        self.fps.update()
        result_image = self.fps.show_fps(image)
        
        return result_image

def main():
    kcf_node = KCFNode('kcf_tracking')
    try:
        rospy.spin()
    except Exception as e:
        kcf_node.mecanum_pub.publish(Twist())
        kcf_node.pan_servo.set_position(PAN_CENTER,  500)
        kcf_node.tilt_servo.set_position(TILT_CENTER, 500)
        rospy.logerr(str(e))

if __name__ == '__main__':
    main()
