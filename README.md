cd WomenSafety
pip install -r requirements.txt
python run_dashboard.py --mode all

in the env file 

Webcam (built-in):
CAMERA_SOURCE=0
(Use 1, 2, etc. if you have multiple cameras)

IP camera (RTSP - most common for CCTV):
CAMERA_SOURCE=rtsp://username:password@192.168.1.100:554/stream1

IP camera (HTTP/MJPEG stream):
CAMERA_SOURCE=http://192.168.1.100:8080/video

Video file:
CAMERA_SOURCE=data/crash.mp4

to enalable disable the detection model set 0/1 in the .env file
0- to dialble detection pipleline in front of certain model
1- to enable detection pipeline for the certain model
