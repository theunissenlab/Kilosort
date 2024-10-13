from qtpy import QtCore, QtWidgets
import numpy as np
import pyqtgraph as pg
import torch

from kilosort.spikedetect import template_centers, nearest_chans
from kilosort.clustering_qr import x_centers, y_centers, get_nearest_centers
from kilosort.gui.logger import setup_logger


logger = setup_logger(__name__)


class ProbeViewBox(QtWidgets.QGroupBox):

    def __init__(self, parent):
        super(ProbeViewBox, self).__init__(parent=parent)
        self.setTitle("Probe View")
        self.gui = parent
        self.probe_view = pg.PlotWidget()
        self.template_toggle = QtWidgets.QCheckBox('Universal Templates')
        self.center_toggle = QtWidgets.QCheckBox('Grouping Centers')
        self.aspect_toggle = QtWidgets.QCheckBox('True Aspect Ratio')
        self.spot_scale = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.setup()

        self.reset_spots_variables()

        self.sorting_status = {
            "preprocess": False,
            "spikesort": False,
            "export": False
        }


    def setup(self):
        self.aspect_toggle.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.aspect_toggle.stateChanged.connect(self.set_layout)
        self.template_toggle.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.template_toggle.stateChanged.connect(self.set_layout)
        self.center_toggle.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.center_toggle.stateChanged.connect(self.set_layout)

        self.spot_scale.setMinimum(0)
        # Actually want 0 to 10 scaling, but these are multiplied by 4
        # to get 0.25 increments.
        self.spot_scale.setMaximum(40)
        self.spot_scale.setValue(4)
        self.spot_scale.valueChanged.connect(self.set_layout)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel('Left click to toggle excluded channels'))
        layout.addWidget(self.probe_view, 95)
        layout.addWidget(self.aspect_toggle)
        layout.addWidget(self.template_toggle)
        layout.addWidget(self.center_toggle)
        layout.addWidget(self.spot_scale)
        self.setLayout(layout)

    def reset_spots_variables(self):
        self.active_layout = None
        self.kcoords = None
        self.xc = None
        self.yc = None
        self.xcup = None
        self.ycup = None
        self.center_positions = None
        self.total_channels = None
        self.channel_spots = None
        self.template_spots = None
        self.center_spots = None
        self.channel_map = None
        self.channel_map_dict = {}

    def set_layout(self):
        self.probe_view.clear()
        self.reset_spots_variables()
        probe = self.gui.settings_box.probe_layout  # original, no removed chans
        template_args = self.gui.settings_box.get_probe_template_args()
        self.update_spots_variables(probe, template_args)
        self.create_plot()

    def update_spots_variables(self, probe, template_args):
        self.active_layout = probe
        # Set xc, yc based on revised probe (with bad channels removed) for
        # determining template and center positions, since that's how they would
        # be placed during sorting.
        probe = self.gui.probe_layout
        self.xc, self.yc = probe['xc'], probe['yc']
        self.kcoords = probe['kcoords']
        if self.template_toggle.isChecked() or self.center_toggle.isChecked():
            self.xcup, self.ycup, self.ops = self.get_template_spots(*template_args)
            self.center_positions = self.get_center_spots()

        # Change xc, yc back to original probe for plotting all channels.
        self.xc, self.yc = self.active_layout["xc"], self.active_layout["yc"]
        self.total_channels = self.active_layout["n_chan"]
        self.channel_map = self.active_layout["chanMap"]
        self.channel_map_dict = {}
        for ind, (xc, yc) in enumerate(zip(self.xc, self.yc)):
            self.channel_map_dict[(xc, yc)] = ind

    def get_template_spots(self, nC, dmin, dminx, max_dist, x_centers, device):
        ops = {
            'yc': self.yc, 'xc': self.xc, 'max_channel_distance': max_dist,
            'x_centers': x_centers, 'settings': {'dmin': dmin, 'dminx': dminx},
            'kcoords': self.kcoords
            }
        ops = template_centers(ops)
        [ys, xs] = np.meshgrid(ops['yup'], ops['xup'])
        ys, xs = ys.flatten(), xs.flatten()
        iC, ds = nearest_chans(ys, self.yc, xs, self.xc, nC, device=device)

        igood = ds[0,:] <= ops['max_channel_distance']**2
        iC = iC[:,igood]
        ds = ds[:,igood]
        ys = ys[igood]
        xs = xs[igood]
        ops['xcup'] = xs
        ops['ycup'] = ys

        return xs, ys, ops

    def get_center_spots(self):
        ycent = y_centers(self.ops)
        xcent = x_centers(self.ops)
        xy = np.vstack((self.ops['xcup'], self.ops['ycup']))
        xy = torch.from_numpy(xy)
        nearest_center = get_nearest_centers(xy, xcent, ycent)

        center_positions = []
        for kk in np.arange(len(ycent)):
            for jj in np.arange(len(xcent)):
                ii = kk + jj*ycent.size
                if ii in nearest_center:
                    center_positions.append((xcent[jj], ycent[kk]))
                else:
                    continue

        return center_positions

    def change_sorting_status(self, status_dict):
        self.sorting_status = status_dict

    def generate_spots_list(self):
        channel_spots = []
        template_spots = []
        center_spots = []
        bad_channels = self.gui.settings_box.get_bad_channels()

        if self.xc is not None:
            size = 10 * self.spot_scale.value()/4
            symbol = "s"
            for x_pos, y_pos in zip(self.xc, self.yc):
                index = self.channel_map_dict[(x_pos, y_pos)]
                channel = self.channel_map[index]
                if channel in bad_channels:
                    color = "b"
                else:
                    color = "g"
                pen = pg.mkPen(0.5)
                brush = pg.mkBrush(color)
                channel_spots.append({
                    'pos': (x_pos, y_pos), 'size': size, 'pen': pen, 'brush': brush,
                    'symbol': symbol
                    })
        self.channel_spots = channel_spots

        if self.xcup is not None:
            size = 5 * self.spot_scale.value()/4
            symbol = "o"
            color = "w"
            for x, y in zip(self.xcup, self.ycup):
                pen = pg.mkPen(0.5)
                brush = pg.mkBrush(color)
                template_spots.append({
                    'pos': (x,y), 'size': size, 'pen': pen, 'brush': brush,
                    'symbol': symbol
                    })
        self.template_spots = template_spots

        if self.center_positions is not None:
            size = 20 * self.spot_scale.value()/4
            symbol = "o"
            color = "y"
            for x, y in self.center_positions:
                pen = pg.mkPen(color=color)
                brush = None
                center_spots.append({
                    'pos': (x,y), 'size': size, 'pen': pen, 'brush': brush,
                    'symbol': symbol
                })
        self.center_spots = center_spots

    def create_plot(self):
        self.generate_spots_list()
        spots = self.channel_spots
        if self.template_toggle.isChecked():
            spots += self.template_spots
        if self.center_toggle.isChecked():
            spots += self.center_spots
        if self.aspect_toggle.isChecked():
            self.probe_view.setAspectLocked()
        else:
            self.probe_view.setAspectLocked(lock=False)

        scatter_plot = pg.ScatterPlotItem(spots)
        scatter_plot.sigClicked.connect(self.on_points_clicked)
        self.probe_view.addItem(scatter_plot)

    def reset(self):
        self.clear_plot()
        self.reset_current_probe_layout()

    def reset_current_probe_layout(self):
        self.active_layout = None
        self.kcoords = None
        self.xc = None
        self.yc = None
        self.total_channels = None
        self.channel_map = None
        self.channel_map_dict = {}

    def prepare_for_new_context(self):
        self.clear_plot()
        self.reset_current_probe_layout()

    def clear_plot(self):
        self.probe_view.getPlotItem().clear()

    @QtCore.Slot(object, object)
    def on_points_clicked(self, points, event):
        selected_point = points.ptsClicked[0]
        x_pos = int(selected_point.pos().x())
        y_pos = int(selected_point.pos().y())

        # Get channel number corresponding to clicked position, use that
        # to update the list of bad channels before refreshing plot.
        index = self.channel_map_dict[(x_pos, y_pos)]
        channel = self.channel_map[index]
        bad_channels = self.gui.settings_box.get_bad_channels()
        if channel in bad_channels:
            # Remove it from the list
            bad_channels.remove(channel)
        else:
            bad_channels.append(channel)
        self.gui.settings_box.set_bad_channels(bad_channels)

        self.set_layout()
