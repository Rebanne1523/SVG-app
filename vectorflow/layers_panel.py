"""The layers panel: a tree of layers / folders / vectors with drag & drop reordering.

Rules (kept deliberately simple, Photoshop-style):
  * Top of the list = in front. Bottom = behind.
  * Folders can nest folders. A "layer" is simply a top-level folder.
  * Clicking a row selects it on the canvas (and vice versa). Selecting a folder or a
    vector makes its folder the target for new drawings ("Drawing in: ...").
  * Drag rows to reorder or to move them into/out of folders. The blue line shows exactly
    where they will land; dropping onto a folder puts them inside it, on top.
  * Eye = show/hide (Alt+click = show only this). Padlock = lock.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QMenu, QSlider, QTabBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .icons import swatch_icon, ui_icon
from .model import Sheet

COL_NAME, COL_EYE, COL_LOCK = 0, 1, 2


CHUNK = 800            # children listed at once under a folder; the rest load on demand
BUDGET = 2500          # items created in one rebuild (folders beyond it stay collapsed until opened)


class NodeItem(QTreeWidgetItem):
    def __init__(self, node):
        super().__init__()
        self.node = node
        self.populated = False
        self.shown = 0           # how many of the node's children are listed (from the top)


class SubItem(QTreeWidgetItem):
    """A sub-path of the compound path being looked into (a view: the drawing is not changed)."""

    def __init__(self, sp, index):
        super().__init__()
        self.sp = sp
        self.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.setText(COL_NAME, f"Sub-path {index}  ({len(sp.anchors)} points)")


class MoreItem(QTreeWidgetItem):
    """"… N more" row at the end of a very long folder: click it to list the next batch."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFlags(Qt.ItemIsEnabled)
        self.setForeground(COL_NAME, QBrush(QColor(140, 170, 210)))
        self.refresh()

    def refresh(self):
        left = len(self.owner.node.children) - self.owner.shown
        self.setText(COL_NAME, f"… {left} more (click to show {min(left, CHUNK)})")


class LayerTree(QTreeWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setColumnCount(3)
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(16, 16))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.setAnimated(False)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(COL_NAME, self.header().ResizeMode.Stretch)
        self.header().setSectionResizeMode(COL_EYE, self.header().ResizeMode.Fixed)
        self.header().setSectionResizeMode(COL_LOCK, self.header().ResizeMode.Fixed)
        self.setColumnWidth(COL_EYE, 28)
        self.setColumnWidth(COL_LOCK, 28)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setFrameShape(QFrame.NoFrame)

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        col = self.columnAt(int(e.position().x()))
        if isinstance(item, MoreItem):
            if e.button() == Qt.LeftButton:
                self.panel.show_more(item)
            return
        if isinstance(item, SubItem):
            super().mousePressEvent(e)
            return
        if item is not None and col in (COL_EYE, COL_LOCK) and e.button() == Qt.LeftButton:
            if col == COL_EYE:
                self.panel.toggle_visible(item.node, bool(e.modifiers() & Qt.AltModifier))
            else:
                self.panel.toggle_lock(item.node)
            return
        if (item is not None and col == COL_NAME and e.button() == Qt.LeftButton and not e.modifiers()
                and isinstance(item, NodeItem) and item.node.is_group() and item.isSelected()
                and len(self.selectedItems()) == 1):
            # a second click on an already selected folder selects every vector inside it
            leaves = []

            def walk(n):
                for c in n.children:
                    if c.is_group():
                        walk(c)
                    elif not c.locked:
                        leaves.append(c)
            walk(item.node)
            if leaves:
                self.panel.get_doc().set_selection(leaves)
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        col = self.columnAt(int(e.position().x()))
        if isinstance(item, (MoreItem, SubItem)):
            return
        if item is not None and col == COL_NAME:
            n = item.node
            if n.kind == "path" and len(n.subpaths) > 1:
                self.panel.get_doc().enter_compound(n)      # double-click a compound path: go inside
            else:
                self.panel.begin_rename(item)
            return
        super().mouseDoubleClickEvent(e)

    def dropEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        pos = self.dropIndicatorPosition()
        nodes = [it.node for it in self.selectedItems() if isinstance(it, NodeItem)]
        e.setDropAction(Qt.IgnoreAction)
        e.accept()
        self.panel.apply_drop(nodes, target.node if isinstance(target, NodeItem) else None, pos)


class LayersPanel(QWidget):
    def __init__(self, get_doc, parent=None):
        super().__init__(parent)
        self.get_doc = get_doc
        self._syncing = False
        self._from_tree = False
        self._building = False
        self.item_of = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.target_label = QLabel()
        self.target_label.setContentsMargins(8, 6, 8, 6)
        self.target_label.setToolTip("New drawings are created inside this layer / folder.\n"
                                     "Select another layer or folder to change it.")
        lay.addWidget(self.target_label)

        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 6)
        row.addWidget(QLabel("Opacity"))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self._opacity_changed)
        row.addWidget(self.opacity, 1)
        self.opacity_label = QLabel("100%")
        self.opacity_label.setMinimumWidth(36)
        row.addWidget(self.opacity_label)
        lay.addLayout(row)

        self.entered = None
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.addTab("Layers")
        self.tabs.setTabButton(0, QTabBar.RightSide, None)
        self.tabs.setVisible(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(lambda i: self.exit_entered())
        lay.addWidget(self.tabs)

        self.tree = LayerTree(self)
        lay.addWidget(self.tree, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        bar.setSpacing(2)
        for icon_name, tip, fn in (
            ("layer", "New layer (top level)", lambda: self.get_doc().new_folder(as_layer=True)),
            ("folder", "New folder inside the current target", lambda: self.get_doc().new_folder()),
            ("group", "Group selection into a folder  (Ctrl+G)", self.group_selection),
            ("dup", "Duplicate  (Ctrl+D)", self.duplicate_selection),
            ("trash", "Delete  (Del)", self.delete_selection),
        ):
            b = QToolButton()
            b.setIcon(ui_icon(icon_name, 18))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.tree.itemSelectionChanged.connect(self._tree_selection)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.itemCollapsed.connect(self._collapsed)
        self.tree.itemChanged.connect(self._renamed)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.connect_doc()
        self.rebuild()

    # ------------------------------------------------------------ document wiring
    def connect_doc(self):
        d = self.get_doc()
        self._doc = d
        d.structureChanged.connect(self.rebuild)
        d.sheetChanged.connect(self.rebuild)
        d.selectionChanged.connect(self.sync_from_doc)
        d.contentChanged.connect(self.refresh_icons)
        d.entered.connect(self.enter)

    def disconnect_doc(self):
        d = getattr(self, "_doc", None)
        if d is None:
            return
        for sig, slot in ((d.structureChanged, self.rebuild), (d.sheetChanged, self.rebuild),
                          (d.selectionChanged, self.sync_from_doc),
                          (d.contentChanged, self.refresh_icons), (d.entered, self.enter)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def set_document(self):
        self.disconnect_doc()
        self.connect_doc()
        self.rebuild()

    # ------------------------------------------------------------ building
    def _make_item(self, node):
        it = NodeItem(node)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsEditable
        if node.is_group():
            flags |= Qt.ItemIsDropEnabled
        it.setFlags(flags)
        self._decorate(it)
        if node.is_group():
            it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator if node.children
                                       else QTreeWidgetItem.DontShowIndicator)
        self.item_of[id(node)] = it
        return it

    def _decorate(self, it):
        n = it.node
        self._building = True
        it.setText(COL_NAME, n.name)
        f = it.font(COL_NAME)
        f.setItalic(not n.visible)
        f.setBold(False)
        it.setFont(COL_NAME, f)
        it.setForeground(COL_NAME, QBrush(QColor(235, 235, 235) if n.visible else QColor(120, 120, 120)))
        if n.is_group():
            it.setIcon(COL_NAME, ui_icon("layer" if isinstance(n.parent, Sheet) else "folder", 16))
        else:
            st = getattr(n, "style", None)
            if n.kind == "measure":
                it.setIcon(COL_NAME, swatch_icon(None, st.stroke if st else None))
            elif st is not None:
                it.setIcon(COL_NAME, swatch_icon(st.fill, st.stroke))
            else:
                it.setIcon(COL_NAME, swatch_icon((120, 120, 120, 255), None))
        it.setIcon(COL_EYE, ui_icon("eye" if n.visible else "eye_off", 16))
        it.setIcon(COL_LOCK, ui_icon("lock" if n.locked else "unlock", 16))
        it.setToolTip(COL_EYE, "Show / hide  (Alt+click: show only this)")
        it.setToolTip(COL_LOCK, "Lock / unlock")
        self._building = False

    def _populate(self, it, budget=None):
        if it.populated:
            return
        it.populated = True
        self._add_children(it, budget)

    def _add_children(self, it, budget=None):
        """List the next batch of ``it``'s children (topmost first)."""
        node = it.node
        kids = node.children
        total = len(kids)
        start = it.shown
        end = min(total, start + CHUNK)
        was_building = self._building
        self._building = True
        old_more = it.child(it.childCount() - 1) if it.childCount() else None
        if isinstance(old_more, MoreItem):
            it.takeChild(it.childCount() - 1)
        for pos in range(start, end):
            c = kids[total - 1 - pos]
            ci = self._make_item(c)
            it.addChild(ci)
            if budget is not None:
                budget[0] -= 1
            if c.is_group() and c.expanded and (budget is None or budget[0] > 0):
                self._populate(ci, budget)
                ci.setExpanded(True)
        it.shown = end
        if end < total:
            it.addChild(MoreItem(it))
        self._building = was_building

    def show_more(self, more):
        owner = more.owner
        self._add_children(owner)

    def enter(self, group):
        self.entered = group
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        self.tabs.addTab("Inside: " + group.name)
        self.tabs.setVisible(True)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(1)
        self.tabs.blockSignals(False)
        self.rebuild()

    def exit_entered(self):
        self.entered = None
        self.get_doc().set_inside_focus(None)
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        self.tabs.setVisible(False)
        self.rebuild()

    def _tab_changed(self, i):
        if i == 0 and self.entered is not None:
            self.exit_entered()

    def _entered_valid(self):
        g = self.entered
        d = self.get_doc()
        if g is None:
            return False
        n = g
        while n is not None and n is not d.root:
            n = n.parent
        return n is d.root and d.sheet_of(g) is d.current_sheet()

    def rebuild(self):
        d = self.get_doc()
        if self.entered is not None and not self._entered_valid():
            self.entered = None
            while self.tabs.count() > 1:
                self.tabs.removeTab(1)
            self.tabs.setVisible(False)
        self._syncing = True
        self._building = True
        self.tree.clear()
        self.item_of = {}
        self._hl = None
        if self.entered is not None and not self.entered.is_group():
            for i, sp in enumerate(self.entered.subpaths, 1):
                it = SubItem(sp, i)
                self.tree.addTopLevelItem(it)
                if sp is d.inside_focus:
                    it.setSelected(True)
            self._building = False
            self._syncing = False
            return
        cur = d.current_sheet()
        top = self.entered if self.entered is not None else cur
        budget = [BUDGET]
        for c in reversed(top.children if top is not None else []):
            it = self._make_item(c)
            self.tree.addTopLevelItem(it)
            if c.is_group() and c.expanded and budget[0] > 0:
                self._populate(it, budget)
                it.setExpanded(True)
        self._building = False
        self._syncing = False
        self.sync_from_doc()

    def refresh_icons(self):
        sel = self.get_doc().selection
        seen = set()

        def upd(n):
            it = self.item_of.get(id(n))
            if it is not None and id(it) not in seen:
                seen.add(id(it))
                try:
                    self._decorate(it)
                except RuntimeError:
                    pass
            if n.is_group() and len(seen) < 400:
                for c in n.children:
                    upd(c)

        for n in sel[:400]:
            upd(n)
        self.opacity.blockSignals(True)
        self.opacity.setValue(int(round(sel[0].opacity * 100)) if sel else 100)
        self.opacity_label.setText(f"{self.opacity.value()}%")
        self.opacity.blockSignals(False)

    # ------------------------------------------------------------ selection sync
    def _ensure_item(self, node):
        it = self.item_of.get(id(node))
        if it is not None:
            return it
        d = self.get_doc()
        if d.sheet_of(node) is not d.current_sheet():
            return None
        chain = [node] + list(node.ancestors())
        chain.reverse()
        # chain[0] is the root group, chain[1] the sheet (not shown: the panel lists the sheet's layers)
        cur = None
        start = 2
        if self.entered is not None:
            if self.entered not in chain:
                return None
            start = chain.index(self.entered) + 1
        for n in chain[start:]:
            it = self.item_of.get(id(n))
            if it is None and cur is not None:
                self._populate(cur)
                it = self.item_of.get(id(n))
            if it is None:
                return None
            if n is not node:
                self._populate(it)
                it.setExpanded(True)
            cur = it
        return cur

    def sync_from_doc(self):
        if self.entered is not None and not self.entered.is_group():
            d = self.get_doc()
            if list(d.selection) != [self.entered]:     # something else was picked: leave the compound view
                self.exit_entered()
            else:
                return
        if self._from_tree:
            self.sync_light()
            return
        d = self.get_doc()
        self._syncing = True
        self.tree.clearSelection()
        last = None
        big = len(d.selection) > 300     # don't build thousands of rows just to highlight them
        sm = self.tree.selectionModel()
        sm.blockSignals(True)
        self.tree.setUpdatesEnabled(False)
        for n in d.selection:
            it = self.item_of.get(id(n)) if big else self._ensure_item(n)
            if it is not None:
                it.setSelected(True)
                last = it
        sm.blockSignals(False)
        self.tree.setUpdatesEnabled(True)
        if last is not None:
            self.tree.scrollToItem(last)
        target = d.active_container()
        self._highlight(target)
        name = target.name
        self.target_label.setText(f"Drawing in: <b>{name}</b>")
        self._syncing = False
        self.refresh_icons()

    def _tree_selection(self):
        if self._syncing:
            return
        if self.entered is not None and not self.entered.is_group():
            subs = [it.sp for it in self.tree.selectedItems() if isinstance(it, SubItem)]
            self.get_doc().set_inside_focus(subs[0] if len(subs) == 1 else None)
            return
        nodes = [it.node for it in self.tree.selectedItems() if isinstance(it, NodeItem)]
        self._from_tree = True
        try:
            self.get_doc().set_selection(nodes)
        finally:
            self._from_tree = False
        self.sync_light()

    def _highlight(self, target):
        prev = getattr(self, "_hl", None)
        if prev is not None:
            try:
                prev.setBackground(COL_NAME, QBrush())
            except RuntimeError:
                pass
        it = self.item_of.get(id(target))
        if it is not None:
            it.setBackground(COL_NAME, QBrush(QColor(60, 90, 130, 90)))
        self._hl = it

    def sync_light(self):
        d = self.get_doc()
        target = d.active_container()
        self._highlight(target)
        self.target_label.setText(f"Drawing in: <b>{target.name}</b>")
        self.refresh_icons()

    def _expanded(self, it):
        if isinstance(it, NodeItem):
            it.node.expanded = True
            self._populate(it)

    def _collapsed(self, it):
        if isinstance(it, NodeItem):
            it.node.expanded = False

    # ------------------------------------------------------------ actions
    def begin_rename(self, it):
        self.tree.editItem(it, COL_NAME)

    def _renamed(self, it, col):
        if self._building or col != COL_NAME or not isinstance(it, NodeItem):
            return
        text = it.text(COL_NAME).strip()
        if text and text != it.node.name:
            d = self.get_doc()
            with d.edit():
                it.node.name = text

    def toggle_visible(self, node, isolate=False):
        d = self.get_doc()
        if isolate:
            others = [n for n in node.parent.children if n is not node]
            restore = all(not n.visible for n in others)
            with d.edit(structure=True):
                for n in others:
                    n.visible = restore
                node.visible = True
            return
        with d.edit(structure=True):
            node.visible = not node.visible

    def toggle_lock(self, node):
        d = self.get_doc()
        with d.edit(structure=True):
            node.locked = not node.locked

    def _targets(self):
        if self.entered is not None and not self.entered.is_group():
            return []           # looking inside a compound: Delete / Group must not act on the whole thing
        return list(self.get_doc().selection)

    def group_selection(self):
        sel = self._targets()
        if sel:
            self.get_doc().group(sel)

    def ungroup_selection(self):
        gs = [n for n in self._targets() if n.is_group() and not self.get_doc().is_layer(n)]
        if gs:
            self.get_doc().ungroup(gs)

    def duplicate_selection(self):
        sel = self._targets()
        if sel:
            self.get_doc().duplicate(sel)

    def delete_selection(self):
        sel = self._targets()
        if sel:
            self.get_doc().delete(sel)

    def _opacity_changed(self, v):
        self.opacity_label.setText(f"{v}%")
        sel = self._targets()
        if sel:
            self.get_doc().apply_style(sel, merge_key="opacity", opacity=v / 100.0)

    def _menu(self, pos: QPoint):
        d = self.get_doc()
        it = self.tree.itemAt(pos)
        if isinstance(it, (SubItem, MoreItem)):
            return
        m = QMenu(self)
        m.addAction("New layer", lambda: d.new_folder(as_layer=True))
        m.addAction("New folder", lambda: d.new_folder())
        if it is not None:
            m.addSeparator()
            m.addAction("Rename\tF2", lambda: self.begin_rename(it))
            m.addAction("Duplicate", self.duplicate_selection)
            m.addAction("Group into folder", self.group_selection)
            if it.node.is_group():
                m.addAction("Ungroup (dissolve folder)", self.ungroup_selection)
                a = m.addAction("Collapse all inside" if it.isExpanded() else "Expand all inside")
                a.triggered.connect(lambda: self._expand_all(it, not it.isExpanded()))
            m.addSeparator()
            m.addAction("Hide" if it.node.visible else "Show", lambda: self.toggle_visible(it.node))
            m.addAction("Unlock" if it.node.locked else "Lock", lambda: self.toggle_lock(it.node))
            m.addAction("Show only this", lambda: self.toggle_visible(it.node, True))
            m.addSeparator()
            m.addAction("Delete", self.delete_selection)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _expand_all(self, it, expand):
        def rec(i):
            if not isinstance(i, NodeItem) or not i.node.is_group():
                return
            if expand:
                self._populate(i)
            i.setExpanded(expand)
            for k in range(i.childCount()):
                rec(i.child(k))
        rec(it)

    # ------------------------------------------------------------ drag & drop
    def apply_drop(self, nodes, target, pos):
        """Move ``nodes`` according to a drop on ``target`` (``pos`` is the QAbstractItemView
        DropIndicatorPosition). Returns True if something moved."""
        d = self.get_doc()
        if not nodes:
            return False
        P = QAbstractItemView.DropIndicatorPosition
        if target is None or pos == P.OnViewport:
            parent, index = (self.entered or d.current_sheet()), 0
        elif pos == P.OnItem and target.is_group():
            parent, index = target, len(target.children)
        elif pos in (P.AboveItem, P.OnItem):
            parent = target.parent
            index = parent.children.index(target) + 1
        else:  # BelowItem
            parent = target.parent
            index = parent.children.index(target)
        if parent is None:
            parent, index = d.current_sheet(), 0
        ok = d.move_nodes(nodes, parent, index)
        if ok:
            parent.expanded = True
        if ok:
            d.set_selection(nodes)
        return ok

    def keyPressEvent(self, e):
        super().keyPressEvent(e)
