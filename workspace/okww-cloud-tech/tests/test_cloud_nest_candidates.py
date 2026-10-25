import unittest
from types import SimpleNamespace
import cv2
import numpy as np
from cloud_nest_candidates import usable


class CandidateTests(unittest.TestCase):
    def test_player_body_rejected_even_when_stable(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertFalse(usable(frame,SimpleNamespace(x=533,y=265,width=173,height=185)))

    def test_thin_hud_circle_is_rejected(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        cv2.circle(frame,(1018,375),48,(100,235,255),3)
        self.assertFalse(usable(frame,SimpleNamespace(x=964,y=320,width=109,height=110)))

    def test_filled_silhouette_outside_player_is_retained(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        cv2.rectangle(frame,(870,250),(930,400),(100,235,255),-1)
        self.assertTrue(usable(frame,SimpleNamespace(x=850,y=220,width=110,height=200)))

    def test_distant_center_target_above_player_is_retained(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertTrue(usable(frame,SimpleNamespace(x=620,y=150,width=40,height=65)))
