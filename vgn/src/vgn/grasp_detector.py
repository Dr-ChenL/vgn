from mayavi import mlab
import numpy as np
from scipy import ndimage
import torch

from vgn.grasp import Grasp
from vgn.utils.transform import Transform, Rotation
from vgn.networks import load_network
from vgn.utils.vis import draw_volume, draw_sample


class GraspDetector(object):
    def __init__(
        self,
        device,
        network_path,
        threshold=0.90,
        gaussian_filter_sigma=1.0,
        max_filter_size=3,
        show_tsdf=False,
        show_qual=False,
        show_detections=False,
    ):
        self.device = device
        self.net = load_network(network_path, device)

        self.threshold = threshold
        self.gaussian_filter_sigma = gaussian_filter_sigma
        self.max_filter_size = max_filter_size

        self.show_tsdf = show_tsdf
        self.show_qual = show_qual
        self.show_detections = show_detections

    def detect_grasps(self, tsdf):
        """Detect grasps in the given volume.
        
        Args:
            tsdf (np.ndarray): A 1x40x40x40 voxel grid with truncated signed distances.

        Returns:
            List of grasp candidates in voxel coordinates and their associated predicted qualities.
        """
        if self.show_tsdf:
            mlab.figure("Input TSDF")
            draw_volume(tsdf.squeeze())

        qual, rot, width = self._predict(tsdf)

        mask = self._filter_grasps(tsdf, qual, rot, width)
        grasps, qualities = self._select_grasps(qual, rot, width, mask)

        if grasps.size > 0:
            grasps, qualities = self._sort_grasps(grasps, qualities)
            if self.show_detections:
                mlab.figure("Detected grasps")
                draw_sample(tsdf, qual, rot, width, mask)

        return grasps, qualities

    def _predict(self, tsdf):
        tsdf = torch.from_numpy(tsdf).unsqueeze(0).to(self.device)

        with torch.no_grad():
            qual, rot, width = self.net(tsdf)

        qual = qual.cpu().squeeze().numpy()
        rot = rot.cpu().squeeze().numpy()
        width = width.cpu().squeeze().numpy() * 10

        return qual, rot, width

    def _filter_grasps(self, tsdf, qual, rot, width):
        qual = qual.copy()

        qual = ndimage.gaussian_filter(qual, sigma=self.gaussian_filter_sigma)
        qual[qual < self.threshold] = 0.0

        if self.show_qual:
            mlab.figure("Processed grasp quality")
            draw_volume(qual)

        max_vol = ndimage.maximum_filter(qual, size=self.max_filter_size)
        qual = np.where(qual == max_vol, qual, 0.0)
        mask = np.where(qual, 1.0, 0.0)

        return mask

    def _select_grasps(self, qual_vol, rot_vol, width_vol, mask):
        grasps, qualities = [], []

        for index in np.argwhere(mask):
            i, j, k = index

            qual = qual_vol[i, j, k]
            ori = Rotation.from_quat(rot_vol[:, i, j, k])
            pos = np.r_[i, j, k]
            width = width_vol[i, j, k]

            grasps.append(Grasp(Transform(ori, pos), width))
            qualities.append(qual)

        return np.asarray(grasps), np.asarray(qualities)

    def _sort_grasps(self, grasps, qualities):
        indices = np.argsort(-qualities)
        grasps = grasps[indices]
        qualities = qualities[indices]
        return grasps, qualities
