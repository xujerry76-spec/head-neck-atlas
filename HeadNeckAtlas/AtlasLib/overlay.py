"""Slice overlays: Qt text boxes and VTK leaders, anchored in physical space."""
import numpy as np
import qt
import slicer
import vtk
from .catalog import STRUCTURES, display_name
from .geometry import interior_anchor, layout_labels, sample_slice
from .slicer_bridge import matrix_array, volume_affine


class SliceOverlay(qt.QObject):
    def __init__(self, session_getter):
        super().__init__()
        self.session_getter = session_getter
        self.view = None
        self.observers, self.labels, self.actors = [], {}, []
        self.mask_cache = None
        self.drag = None
        self.positions = {}
        self.timer = qt.QTimer()
        self.timer.setSingleShot(True)
        self.timer.connect('timeout()', self.update)

    def bind(self):
        self.close()
        widget = slicer.app.layoutManager().sliceWidget('Red')
        if not widget:
            return
        self.view = widget.sliceView()
        self.slice_node = widget.mrmlSliceNode()
        self.renderer = self.view.renderWindow().GetRenderers().GetFirstRenderer()
        self.view.installEventFilter(self)
        self.observers.append((self.slice_node, self.slice_node.AddObserver(vtk.vtkCommand.ModifiedEvent, self.schedule)))
        session = self.session_getter()
        if session.active:
            self.observers.append((session.active, session.active.AddObserver(vtk.vtkCommand.ModifiedEvent, self.invalidate)))
            seg = session.active.GetSegmentation()
            self.observers.append((seg, seg.AddObserver(vtk.vtkCommand.ModifiedEvent, self.invalidate)))
            for event in (slicer.vtkSegmentation.SegmentModified, slicer.vtkSegmentation.RepresentationModified,
                          slicer.vtkSegmentation.SourceRepresentationModified):
                self.observers.append((seg, seg.AddObserver(event, self.invalidate)))
        for name in STRUCTURES:
            label = qt.QLabel(display_name(name), self.view)
            label.setStyleSheet('QLabel {color:#e6edf3;background:#172635;border:1px solid #38566c;border-radius:3px;padding:2px;}')
            label.setToolTip(name + '\n拖动文字改变显示位置；边界请在 Segment Editor 修改。')
            label.installEventFilter(self)
            label.hide()
            self.labels[name] = label
        self.schedule()

    def invalidate(self, *args):
        self.mask_cache = None
        self.schedule()

    def schedule(self, *args):
        if not self.timer.isActive():
            self.timer.start(80)

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == qt.QEvent.Resize:
            self.schedule()
        name = next((name for name, label in self.labels.items() if obj is label), None)
        if not name:
            return False
        if event.type() == qt.QEvent.MouseButtonPress and event.button() == qt.Qt.LeftButton:
            point = event.globalPos()
            session = self.session_getter()
            self.drag = (name, point.x(), point.y(), list(session.offsets.get(name, [0, 0])))
            return True
        if event.type() == qt.QEvent.MouseMove and self.drag:
            name, x, y, previous = self.drag
            point = event.globalPos()
            self.session_getter().offsets[name] = [previous[0] + point.x()-x, previous[1] + point.y()-y]
            self.schedule()
            return True
        if event.type() == qt.QEvent.MouseButtonRelease and self.drag:
            self.drag = None
            self.session_getter().persist()
            self.schedule()
            return True
        return False

    def update(self):
        if not self.view:
            return
        session = self.session_getter()
        for label in self.labels.values():
            label.hide()
        for actor in self.actors:
            self.renderer.RemoveActor2D(actor)
        self.actors = []
        if not session.volume or not session.active:
            self.view.scheduleRender()
            return
        if self.mask_cache is None:
            self.mask_cache = session.slice_masks()
        width, height = int(self.view.width), int(self.view.height)
        if width < 40 or height < 40:
            return
        affine = volume_affine(session.volume)
        xy = matrix_array(self.slice_node.GetXYToRAS())
        # A 2-pixel grid keeps interactions responsive; coordinates remain physical.
        step = 2
        scaled = xy @ np.diag([step, step, 1, 1])
        items = []
        for name, (mask, mask_affine) in self.mask_cache.items():
            if name in session.hidden:
                continue
            anchor = interior_anchor(sample_slice(mask, mask_affine, scaled, (width+1)//step, (height+1)//step))
            if anchor:
                items.append({'id': name, 'anchor': (anchor[0]*step, height-1-anchor[1]*step)})
        self.positions = {}
        for item in layout_labels(items, width, height, session.offsets):
            if item['hidden']:
                continue
            name = item['id']
            x, y = item['position']
            box_width, box_height = item['size']
            label = self.labels[name]
            label.setGeometry(int(x), int(y), box_width, box_height)
            label.show()
            label.raise_()
            self.positions[name] = (x, y)
            anchor_x, anchor_y = item['anchor']
            end_x = x+box_width if anchor_x >= x+box_width else x
            points = vtk.vtkPoints()
            points.InsertNextPoint(anchor_x, height-1-anchor_y, 0)
            points.InsertNextPoint(end_x, height-1-(y+box_height/2), 0)
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(2)
            lines.InsertCellPoint(0)
            lines.InsertCellPoint(1)
            poly = vtk.vtkPolyData()
            poly.SetPoints(points)
            poly.SetLines(lines)
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputData(poly)
            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)
            color = session.active.GetSegmentation().GetSegment(name).GetColor()
            actor.GetProperty().SetColor(*color)
            actor.GetProperty().SetLineWidth(1.5)
            self.renderer.AddActor2D(actor)
            self.actors.append(actor)
        self.view.scheduleRender()

    def close(self):
        self.timer.stop()
        self.drag = None
        for obj, tag in self.observers:
            obj.RemoveObserver(tag)
        self.observers = []
        for label in self.labels.values():
            label.removeEventFilter(self)
            label.hide()
            label.deleteLater()
        self.labels = {}
        if self.view:
            self.view.removeEventFilter(self)
            for actor in self.actors:
                self.renderer.RemoveActor2D(actor)
            self.view.scheduleRender()
        self.actors, self.positions = [], {}
        self.mask_cache = None
        self.view = None
