#include "usb_camera_recovery.h"
#include <cassert>
#include <string>
int main(){
 using A=UsbCameraRecovery::Action;
 UsbCameraRecovery r;r.OnFrame();r.OnDisconnected(0);
 assert(r.Poll(4999)==A::kNone);assert(r.Poll(5000)==A::kStop);assert(r.Poll(5000)==A::kNone);
 r.Stopped(true,5000);assert(r.Poll(5249)==A::kNone);assert(r.Poll(5250)==A::kStart);
 r.Started(true,5250);r.OnFrame();assert(r.Poll(20000)==A::kNone);
 r.OnDisconnected(20000);assert(r.Poll(25000)==A::kStop);r.Stopped(false,25000);
 assert(r.Poll(99999)==A::kNone);assert(std::string(r.Error())=="usb_stop_failed");
 UsbCameraRecovery exhausted;exhausted.OnDisconnected(0);
 for(int i=0;i<3;++i){auto t=5000+i*5250;assert(exhausted.Poll(t)==A::kStop);exhausted.Stopped(true,t);assert(exhausted.Poll(t+250)==A::kStart);exhausted.Started(false,t+250);}
 assert(exhausted.Poll(50000)==A::kNone);assert(std::string(exhausted.Error())=="usb_recovery_exhausted");
 UsbCameraRecovery c;c.OnDisconnected(0);c.Close();assert(c.Poll(50000)==A::kNone);
}

