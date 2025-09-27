import os
import sys

if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

import tkinter as tk
from tkinter import filedialog, messagebox
import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

RARITIES = ["Abundant", "Common", "Uncommon", "Rare", "VeryRare", "ExtremelyRare"]
RARITY_WEIGHTS = {
    "Abundant": 32,
    "Common": 16,
    "Uncommon": 8,
    "Rare": 4,
    "VeryRare": 2,
    "ExtremelyRare": 1
}

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_suggestions():
    try:
        with open(resource_path("Items.txt"), "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


SUGGESTED_NAMES = load_suggestions()

class NodeTreeApp(tk.Tk):
    def collapse_all(self):
        for item in self.treeview.get_children():
            self._recursive_collapse(item)

    def _recursive_collapse(self, item):
        self.treeview.item(item, open=False)
        for child in self.treeview.get_children(item):
            self._recursive_collapse(child)

    def expand_all(self):
        for item in self.treeview.get_children():
            self._recursive_expand(item)

    def _recursive_expand(self, item):
        self.treeview.item(item, open=True)
        for child in self.treeview.get_children(item):
            self._recursive_expand(child)
    def __init__(self):
        super().__init__()
        self.title("SCUM Node Editor")
        self.geometry("800x600")

        from tkinter import ttk

        self.toolbar = tk.Frame(self)
        self.toolbar.pack(fill=tk.X, side=tk.TOP)

        self.tree_frame = tk.Frame(self)
        self.tree_frame.pack(fill=tk.BOTH, expand=True)

        self.treeview = ttk.Treeview(self.tree_frame, columns=("rarity", "postspawn"), show="tree headings")
        self.treeview.heading("#0", text="Name")
        self.treeview.heading("rarity", text="Rarity")
        self.treeview.heading("postspawn", text="PostSpawnActions")
        self.treeview.pack(side="left", fill="both", expand=True)
        self.treeview.bind("<Button-3>", self.on_treeview_right_click)
            
        self.treeview.bind("<Delete>", self.on_treeview_delete)
        self.treeview.tag_configure("group0", background="#f0f0f0")  # light gray
        self.treeview.tag_configure("group1", background="#ffffff")  # white
        style = ttk.Style()
        style.map("Treeview",
            background=[("selected", "#3399FF")],  # Bright blue
            foreground=[("selected", "white")]
        )
        style = ttk.Style()
        style.theme_use("default")

        style.map("Treeview",
            background=[("selected", "#3399FF")],
            foreground=[("selected", "white")]
        )

        style.configure("Treeview", rowheight=22)

        # Hover support
        self.treeview.tag_configure("hover", background="#d0e7ff")
        self._last_hovered_row = None
        self._last_hovered_row_tag = None
        self.treeview.bind("<Motion>", self._on_tree_motion)

        self.tree_scroll = tk.Scrollbar(self.tree_frame, orient="vertical", command=self.treeview.yview)
        self.tree_scroll.pack(side="right", fill="y")
        self.treeview.configure(yscrollcommand=self.tree_scroll.set)

        tk.Button(self.toolbar, text="Load JSON", command=self.load_json).pack(side=tk.LEFT, padx=0)
        tk.Button(self.toolbar, text="Expand All", command=self.expand_all).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="Collapse All", command=self.collapse_all).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="Undo", command=self.undo_last_change).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="Clear", command=self.clear_tree).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="Visual", command=self.start_drilldown).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="Save", command=self.save_json).pack(side=tk.RIGHT, padx=5)
        tk.Button(self.toolbar, text="Save As", command=self.save_as).pack(side=tk.RIGHT, padx=5)

        self.protocol("WM_DELETE_WINDOW", self.on_main_close)

        self.node_tree = None
        self.tree_paths = {}
        self.node_widgets = {}
        self.undo_stack = []

        # Footer credit
        credit_label = tk.Label(self, text="version 1.0 | Created by Genaxx | Discord:Genaxx", font=("Segoe UI", 8), fg="gray")
        credit_label.pack(side="bottom", pady=2)

# Helpers
    def _get_expanded_labels(self):
        expanded = set()
        def collect(item):
            if self.treeview.item(item, 'open'):
                expanded.add(self.treeview.item(item, 'text'))
            for child in self.treeview.get_children(item):
                collect(child)
        for item in self.treeview.get_children():
            collect(item)
        return expanded

    def on_treeview_delete(self, event):
        item_id = self.treeview.focus()
        if not item_id:
            return
        node = self.find_node_by_item_id(item_id)
        if not node:
            return
        self.remove_node_for_node(node)


    def _restore_expanded_labels(self, expanded_labels):
        def restore(item):
            if self.treeview.item(item, 'text') in expanded_labels:
                self.treeview.item(item, open=True)
            for child in self.treeview.get_children(item):
                restore(child)
        for item in self.treeview.get_children():
            restore(item)

    def on_treeview_right_click(self, event):
        item_id = self.treeview.identify_row(event.y)
        column = self.treeview.identify_column(event.x)
        if not item_id:
            return

        node = self.find_node_by_item_id(item_id)
        if not node:
            return

        menu = tk.Menu(self, tearoff=0)
        rarity_menu = tk.Menu(menu, tearoff=0)
        for rarity in RARITIES:
            rarity_menu.add_command(
                label=rarity,
                command=lambda r=rarity: self.set_rarity_for_node(node, r, item_id)
            )
        menu.add_command(label="✏️ Edit Name", command=lambda: self.edit_name_for_node(node, item_id))
        menu.add_command(label="🛠 Edit PostSpawnActions", command=lambda: self.edit_postspawn_for_node(node, item_id))
        menu.add_cascade(label="🔄 Change Rarity", menu=rarity_menu)
        menu.add_command(label="➕ Add Child", command=lambda: self.add_child_for_node(node))
        menu.add_command(label="🗑 Remove Node", command=lambda: self.remove_node_for_node(node))
        
        # Re-apply hover highlight after menu closes
        def restore_hover():
            self._on_tree_motion(event)
        self.after(100, restore_hover)

        menu.tk_popup(event.x_root, event.y_root)

# UI Stuff
    def _on_tree_motion(self, event):
        row_id = self.treeview.identify_row(event.y)
        if row_id == self._last_hovered_row:
            return

        # Remove previous hover tag
        if self._last_hovered_row:
            if self._last_hovered_row_tag:
                if self.treeview.exists(self._last_hovered_row):
                    self.treeview.item(self._last_hovered_row, tags=(self._last_hovered_row_tag,))

            else:
                self.treeview.item(self._last_hovered_row, tags=())

        # Set new hover tag
        if row_id:
            tags = self.treeview.item(row_id, "tags")
            self._last_hovered_row_tag = tags[0] if tags else ""
            self.treeview.item(row_id, tags=("hover",))
            self._last_hovered_row = row_id  # ✅ track the current row


    def _on_mousewheel(self, event):
        self.tree_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
     
    def start_drilldown(self):
        if not self.node_tree:
            messagebox.showinfo("No Data", "Please load a node tree first.")
            return
        self.chart_fig, self.chart_ax = plt.subplots(figsize=(8, 6))
        try:
            self.chart_fig.canvas.manager.set_window_title(self.loaded_filename)
        except Exception:
            pass
        self.chart_fig.canvas.manager.set_window_title(self.loaded_filename if hasattr(self, 'loaded_filename') else "Loot Pie")  # Temporary size
        self.chart_fig.canvas.mpl_connect("button_press_event", self.on_chart_click)
        self.drill_entries = []
        
        self.drill_path_stack = [(self.node_tree, "ItemLootTreeNodes")]
        self.open_drilldown_chart(self.node_tree, "ItemLootTreeNodes")
        plt.show()

    def on_chart_click(self, event):
        if event.button == 3:  # Right click for context menu
            if hasattr(self, 'drill_wedges') and self.drill_wedges and self.drill_entries:
                for i, wedge in enumerate(self.drill_wedges):
                    if wedge.contains(event)[0]:
                        self.show_context_menu(event, i)
                        return
        # Ignore empty or resize-triggered events
        if event.x is None or event.y is None:
            return

        # Handle back click zone
        if hasattr(self, 'back_text') and self.back_text and self.back_text.figure and self.back_text.contains(event)[0]:
            if len(self.drill_path_stack) > 1:
                self.drill_path_stack.pop()
                parent, path = self.drill_path_stack[-1]
                self.open_drilldown_chart(parent, path)
            return

        # Handle drilldown click
        if hasattr(self, 'drill_wedges') and self.drill_wedges and self.drill_entries and self.drill_entries[0][0] != "No lootable items":
            for i, wedge in enumerate(self.drill_wedges):
                if wedge.contains(event)[0] and self.drill_entries[i][3]:
                    _, _, child, _ = self.drill_entries[i]
                    new_path = self.drill_path_stack[-1][1] + "." + child["Name"]
                    self.drill_path_stack.append((child, new_path))
                    self.open_drilldown_chart(child, new_path)
                    break

    def open_drilldown_chart(self, parent_node, node_path):
        self.hover_info = {}
        self.chart_fig.clf()
        self.chart_ax = self.chart_fig.add_subplot(111)
        

        # Reset all dynamic state
        self.tooltip_sources = []
        self.tooltip_annotations = []
        self.breadcrumb_texts = []
        # Clear previous motion listener if it exists
        if hasattr(self, "motion_event_id"):
            self.chart_fig.canvas.mpl_disconnect(self.motion_event_id)

        self.tooltip_annotations = []

        def on_back(event):
            if len(self.drill_path_stack) > 1:
                self.drill_path_stack.pop()
                parent, path = self.drill_path_stack[-1]
                self.open_drilldown_chart(parent, path)

        self.chart_fig.canvas.mpl_connect("key_press_event", on_back)
        self.chart_ax.clear()

        # Remove old title
        self.chart_ax.set_title("")

        self.tooltip_annotations = []
        self.tooltip_sources = []  # NEW: keep matching label Text objects

        # Clear old breadcrumbs
        for txt in getattr(self, 'breadcrumb_texts', []):
            try:
                if txt.figure:
                    txt.remove()
            except:
                pass
        self.breadcrumb_texts = []

        self.tooltip_annotations = []
        self.tooltip_sources = []

        # Get renderer to compute text sizes
        canvas = self.chart_fig.canvas
        renderer = canvas.get_renderer()

        # Starting x pixel position
        x_px = 10
        y_px = self.chart_fig.bbox.height - 30  # 30px down from top

        for i, (_, path) in enumerate(self.drill_path_stack):
            label = path.split(".")[-1]
            is_last = (i == len(self.drill_path_stack) - 1)
            color = '#d6f5d6' if is_last else 'white'

            # Draw label temporarily at 0,0 just to measure
            temp_text = self.chart_ax.text(
                0, 0, label,
                fontsize=10,
                ha="left", va="center",
                transform=self.chart_fig.transFigure
            )
            bb = temp_text.get_window_extent(renderer=renderer)
            width = bb.width
            temp_text.remove()

            # Convert pixel to figure fraction
            x_frac = x_px / self.chart_fig.bbox.width
            y_frac = y_px / self.chart_fig.bbox.height

            txt = self.chart_ax.text(
                x_frac, y_frac, label,
                fontsize=10,
                ha="left", va="center",
                transform=self.chart_fig.transFigure,
                bbox=dict(facecolor=color, edgecolor='black', boxstyle='round,pad=0.3'),
                picker=True
            )
            self.breadcrumb_texts.append(txt)
            self.tooltip_sources.append(txt)

            # Tooltip
            tip = self.chart_ax.annotate(
                f"Go to: {label}",
                xy=(x_frac, y_frac),
                xytext=(x_frac, y_frac - 0.03),
                textcoords="figure fraction",
                ha="left", va="center", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.0),
                visible=False,
                transform=self.chart_fig.transFigure
            )
            self.tooltip_annotations.append(tip)

            x_px += int(width) + 5  # 1px space after label

            # Draw arrow if not last
            if not is_last:
                arrow_text = "→"
                temp_arrow = self.chart_ax.text(0, 0, arrow_text, fontsize=10,
                                                ha="left", va="center",
                                                transform=self.chart_fig.transFigure)
                arrow_bb = temp_arrow.get_window_extent(renderer=renderer)
                arrow_width = arrow_bb.width
                temp_arrow.remove()

                arrow = self.chart_ax.text(
                    x_px / self.chart_fig.bbox.width,
                    y_frac,
                    arrow_text,
                    fontsize=10,
                    ha="left", va="center",
                    transform=self.chart_fig.transFigure
                )
                self.breadcrumb_texts.append(arrow)

                x_px += int(arrow_width) + 7  # 1px space after arrow

        children = parent_node.get("Children", [])
        entries = [(child["Name"], child.get("Rarity"), child) for child in children if child.get("Rarity") in RARITY_WEIGHTS]

        def on_breadcrumb_click(event):
            if not hasattr(self, "breadcrumb_texts"):
                return
            for i, txt in enumerate(self.breadcrumb_texts):

                if txt.contains(event)[0]:
                    # Each label is at 2*i (labels and separators alternate)
                    logical_index = i // 2
                    if logical_index < len(self.drill_path_stack):
                        self.drill_path_stack = self.drill_path_stack[:logical_index + 1]
                        node, path = self.drill_path_stack[-1]
                        self.open_drilldown_chart(node, path)
                        return
        if hasattr(self, 'breadcrumb_click_cid'):
            self.chart_fig.canvas.mpl_disconnect(self.breadcrumb_click_cid)

        self.breadcrumb_click_cid = self.chart_fig.canvas.mpl_connect("button_press_event", on_breadcrumb_click)
            

        if not entries:
            self.drill_entries = [("No lootable items", "ExtremelyRare", parent_node)]
            dynamic_height = max(6, len(self.drill_entries) * 0.35)
            self.chart_fig.set_size_inches(8, dynamic_height)
            wedges = self.chart_ax.pie([1], labels=["No lootable items"], colors=['lightgray'])
            self.drill_wedges = wedges[0]
            self.chart_ax.set_title(f"{node_path} (No rarity-annotated children)")
            if len(self.drill_path_stack) > 1:
                if hasattr(self, 'back_text') and self.back_text in self.chart_ax.texts:
                    self.back_text.remove()
                self.back_text = self.chart_ax.text(
                    0, -1.2, "[Back]",
                    ha="center", fontsize=10,
                    bbox=dict(facecolor='lightgray', edgecolor='black')
                )
            else:
                if hasattr(self, 'back_text'):
                    try:
                        self.back_text.remove()
                    except Exception:
                        pass
                    self.back_text = None
            self.chart_ax.axis("equal")
            self.chart_ax.set_position([0.05, 0.1, 0.9, 0.8])
            self.chart_fig.canvas.draw()
            return

        self.drill_entries = []
        for name, rarity, child in entries:
            has_valid_children = any(
                c.get("Rarity") in RARITY_WEIGHTS or c.get("Children")
                for c in child.get("Children", [])
            )
            self.drill_entries.append((name, rarity, child, has_valid_children))

        cmap = plt.get_cmap('RdYlGn')
        rarity_color_map = {
            "Abundant": cmap(1.0),
            "Common": cmap(0.8),
            "Uncommon": cmap(0.6),
            "Rare": cmap(0.4),
            "VeryRare": cmap(0.2),
            "ExtremelyRare": cmap(0.0)
        }

        labels = [f"{{}} ({{}})".format(name, rarity) for name, rarity, *_ in self.drill_entries]
        sizes = [RARITY_WEIGHTS[rarity] for _, rarity, *_ in self.drill_entries]

        import matplotlib.colors as mcolors

        def fade_color(base_color, alpha=1.0):
            r, g, b = mcolors.to_rgb(base_color)
            brightness = 0.6  # Reduce to ~60% brightness
            return (r * brightness, g * brightness, b * brightness)

        base_colors = [
            "#E6C229",  # Saffron
            "#F17105",  # Pumpkin
            "#D11149",  # Cardinal
            "#6610F2",  # Electric Indigo
            "#1A8FE3",  # Tufts Blue
            "#9C27B0",  # Amethyst
            "#4CAF50",  # Green
            "#FF9800",  # Orange
            "#795548",  # Brown
            "#607D8B"   # Blue Gray
        ]
        colors = []
        for i, (*_, clickable) in enumerate(self.drill_entries):
            base = base_colors[i % len(base_colors)]
            colors.append(base if clickable else fade_color(base))
        self.drill_wedges, texts, autotexts = self.chart_ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            colors=colors,
            labeldistance=1.15,
            pctdistance=0.75,
            center=(0.5, 0.20),
            radius=0.35
        )
        # Attach extra info for hover tooltips
        for wedge, (_, _, child, _) in zip(self.drill_wedges, self.drill_entries):
            subchildren = child.get("Children", [])
            parts = []
            total = 0
            for sub in subchildren:
                rarity = sub.get("Rarity")
                if rarity in RARITY_WEIGHTS:
                    total += RARITY_WEIGHTS[rarity]

            for sub in subchildren:
                name = sub.get("Name", "Unnamed")
                rarity = sub.get("Rarity")
                if rarity in RARITY_WEIGHTS and total > 0:
                    pct = (RARITY_WEIGHTS[rarity] / total) * 100
                    parts.append(f"{name}: {pct:.0f}%")
            
            self.hover_info[wedge] = "\n".join(parts) if parts else "No children"

        # Prepare wedge-based hover box (if not already created)
        # Always recreate hover_annotation for the new chart_ax
        self.hover_annotation = self.chart_ax.annotate(
            "",
            xy=(0, 0),
            xytext=(20, 20),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="lightyellow", ec="black", lw=0.5),
            fontsize=8,
            visible=False
        )


        self.wedge_hover_info = {}
        for wedge, (_, _, child, _) in zip(self.drill_wedges, self.drill_entries):
            subchildren = child.get("Children", [])
            weighted_subs = []
            total = sum(RARITY_WEIGHTS.get(c.get("Rarity"), 0) for c in subchildren)

            for sub in subchildren:
                name = sub.get("Name", "Unnamed")
                rarity = sub.get("Rarity")
                weight = RARITY_WEIGHTS.get(rarity)
                if weight and total > 0:
                    pct = (weight / total) * 100
                    weighted_subs.append((pct, name))

            # Sort descending by % (largest first)
            weighted_subs.sort(reverse=True)

            parts = [f"{name}: {pct:.0f}%" for pct, name in weighted_subs]

            self.wedge_hover_info[wedge] = "\n".join(parts) if parts else "No children"


        for i, (_, rarity, *_), text in zip(range(len(self.drill_entries)), self.drill_entries, texts):
            rarity_color = rarity_color_map.get(rarity, 'lightgray')
            text.set_bbox(dict(boxstyle='round,pad=0.3', facecolor=rarity_color, alpha=0.5))
        tooltip_labels = [
            "" if clickable else ""
            for *_, clickable in self.drill_entries
        ]
        self.tooltip_annotations = []

        for i, wedge in enumerate(self.drill_wedges):
            x, y = wedge.center
            ang = (wedge.theta2 + wedge.theta1) / 2
            rx, ry = 0.7 * np.cos(np.radians(ang)), 0.7 * np.sin(np.radians(ang))
            annotation = self.chart_ax.annotate(
                tooltip_labels[i],
                xy=(rx, ry),
                xytext=(rx * 1.2, ry * 1.2),
                textcoords='data',
                ha='center', va='center', fontsize=8,
                bbox=dict(boxstyle='round,pad=0.3', fc='yellow', alpha=0.0),
                arrowprops=dict(arrowstyle='->', color='gray', alpha=0.0)
            )
            self.tooltip_annotations.append(annotation)

        def on_motion(event):
            if not hasattr(self, "tooltip_sources"):
                return

            any_tooltip_visible = False
            for i, txt in enumerate(self.tooltip_sources):
                try:
                    vis = txt.contains(event)[0]
                    self.tooltip_annotations[i].set_visible(vis)
                    self.tooltip_annotations[i].set_alpha(0.8 if vis else 0.0)
                    any_tooltip_visible |= vis
                except Exception:
                    continue

            # Handle pie wedge hover box
            if hasattr(self, "wedge_hover_info") and event.inaxes == self.chart_ax:
                for wedge in self.wedge_hover_info:
                    if wedge.contains_point((event.x, event.y)):
                        self.hover_annotation.xy = (event.xdata, event.ydata)
                        self.hover_annotation.set_text(self.wedge_hover_info[wedge])
                        self.hover_annotation.set_visible(True)
                        break
                else:
                    self.hover_annotation.set_visible(False)
            else:
                self.hover_annotation.set_visible(False)

            self.chart_fig.canvas.draw_idle()

        self.motion_event_id = self.chart_fig.canvas.mpl_connect("motion_notify_event", on_motion)
        self.chart_ax.axis("equal")
        self.chart_ax.set_position([0.05, 0.1, 0.9, 0.8])
        self.chart_fig.canvas.draw()

    def show_context_menu(self, event, index):
        menu = tk.Menu(self, tearoff=0)
        rarity_menu = tk.Menu(menu, tearoff=0)
        for rarity in RARITIES:
            rarity_menu.add_command(
                label=rarity,
                command=lambda r=rarity: self.set_rarity(index, r)
            )
        menu.add_command(label="✏️ Edit Name", command=lambda: self.edit_name_from_pie(index))
        menu.add_command(label="🛠 Edit PostSpawnActions", command=lambda: self.edit_postspawn_from_pie(index))
        menu.add_cascade(label="🔄 Change Rarity", menu=rarity_menu)
        menu.add_command(label="➕ Add Child", command=lambda: self.add_child(index))
        menu.add_command(label="🗑 Remove Node", command=lambda: self.remove_node(index))
        menu.tk_popup(event.guiEvent.x_root, event.guiEvent.y_root)

    def on_main_close(self):
        try:
            # Close only this instance's figure if it exists
            if hasattr(self, 'chart_fig') and self.chart_fig:
                plt.close(self.chart_fig)  # Only close this specific figure
        except Exception:
            pass
        self.destroy()


# Edit Object Names
    def edit_name_for_node(self, node, item_id):
        expanded_labels = set()

        def collect_expanded(item):
            if self.treeview.item(item, 'open'):
                expanded_labels.add(self.treeview.item(item, 'text'))
            for child in self.treeview.get_children(item):
                collect_expanded(child)
        for item in self.treeview.get_children():
            collect_expanded(item)

        def restore_and_refresh():
            self.clear_tree()
            self.render_node(self.node_tree)
            def restore(item):
                if self.treeview.item(item, 'text') in expanded_labels:
                    self.treeview.item(item, open=True)
                for child in self.treeview.get_children(item):
                    restore(child)
            for item in self.treeview.get_children():
                restore(item)
            self._refresh_pie_if_open()

        self.edit_name_dialog(node, restore_and_refresh)

    def edit_name_from_pie(self, index):
        node = self.drill_entries[index][2]
        if not node:
            return

        expanded = self._get_expanded_labels()

        def refresh():
            self.clear_tree()
            self.render_node(self.node_tree)
            self._restore_expanded_labels(expanded)
            self._refresh_pie_if_open()

        self.edit_name_dialog(node, refresh)

    def edit_name_dialog(self, node, refresh_callback):
        popup = tk.Toplevel(self)
        popup.title("Edit Node Name")
        popup.geometry("300x120")
        popup.grab_set()

        tk.Label(popup, text="New Name:").pack(pady=5)
        entry = tk.Entry(popup)
        entry.insert(0, node.get("Name", ""))
        entry.pack(pady=5)

        def submit():
            new_name = entry.get().strip()
            if not new_name:
                messagebox.showerror("Invalid Name", "Name cannot be empty.")
                return

            import copy
            self.undo_stack.append(copy.deepcopy(self.node_tree))
            node["Name"] = new_name
            refresh_callback()
            popup.destroy()

        tk.Button(popup, text="Rename", command=submit).pack(pady=10)

# Edit PostSpawnActions
    def edit_postspawn_for_node(self, node, item_id):
        expanded_labels = set()

        def collect_expanded(item):
            if self.treeview.item(item, 'open'):
                expanded_labels.add(self.treeview.item(item, 'text'))
            for child in self.treeview.get_children(item):
                collect_expanded(child)
        for item in self.treeview.get_children():
            collect_expanded(item)

        def restore_and_refresh():
            self.clear_tree()
            self.render_node(self.node_tree)
            def restore(item):
                if self.treeview.item(item, 'text') in expanded_labels:
                    self.treeview.item(item, open=True)
                for child in self.treeview.get_children(item):
                    restore(child)
            for item in self.treeview.get_children():
                restore(item)
            self._refresh_pie_if_open()

        self.edit_postspawn_dialog(node, restore_and_refresh)

    def edit_postspawn_from_pie(self, index):
        node = self.drill_entries[index][2]
        if not node:
            return

        expanded = self._get_expanded_labels()

        def refresh():
            self.clear_tree()
            self.render_node(self.node_tree)
            self._restore_expanded_labels(expanded)
            self._refresh_pie_if_open()

        self.edit_postspawn_dialog(node, refresh)

    def _refresh_pie_if_open(self):
        if hasattr(self, 'drill_path_stack'):
            current_node, current_path = self.drill_path_stack[-1]
            try:
                self.chart_ax.clear()
                self.open_drilldown_chart(current_node, current_path)
            except:
                self.drill_path_stack = [(self.node_tree, "ItemLootTreeNodes")]
                self.chart_ax.clear()
                self.open_drilldown_chart(self.node_tree, "ItemLootTreeNodes")

    def edit_postspawn_dialog(self, node, refresh_callback):
        popup = tk.Toplevel(self)
        popup.title("Edit PostSpawnActions")
        popup.geometry("400x200")
        popup.grab_set()

        tk.Label(popup, text="Comma-separated actions:").pack(pady=5)
        entry_widget = tk.Entry(popup, width=50)
        current = ", ".join(node.get("PostSpawnActions", []))
        entry_widget.insert(0, current)
        entry_widget.pack(pady=5)

        def submit():
            import copy
            self.undo_stack.append(copy.deepcopy(self.node_tree))

            actions = [a.strip() for a in entry_widget.get().split(",") if a.strip()]
            node["PostSpawnActions"] = actions

            refresh_callback()
            popup.destroy()

        tk.Button(popup, text="Apply", command=submit).pack(pady=10)

# Rarity
    def set_rarity_for_node(self, node, rarity, item_id):
        import copy
        self.undo_stack.append(copy.deepcopy(self.node_tree))

        expanded = self._get_expanded_labels()

        self.treeview.set(item_id, "rarity", rarity)
        node["Rarity"] = rarity

        self.clear_tree()
        self.render_node(self.node_tree)
        self._restore_expanded_labels(expanded)

        self._refresh_pie_if_open()

    def set_rarity(self, index, new_rarity):
        entry = self.drill_entries[index]
        node = entry[2]
        if node is None:
            return
        import copy
        self.undo_stack.append(copy.deepcopy(self.node_tree))
        expanded = self._get_expanded_labels()
        node["Rarity"] = new_rarity

        node_id = ""
        for path, obj in self.tree_paths.items():
            if obj is node:
                node_id = path
                break

        if node_id:
            # update treeview item rarity value
            for item in self.treeview.get_children(""):
                self._set_rarity_recursive(item, node["Name"], new_rarity)
        else:
            expanded_labels = set()
            def collect_expanded(item):
                if self.treeview.item(item, 'open'):
                    expanded_labels.add(self.treeview.item(item, 'text'))
                for child in self.treeview.get_children(item):
                    collect_expanded(child)
            for item in self.treeview.get_children():
                collect_expanded(item)

            self.clear_tree()
            self.render_node(self.node_tree)
            self._restore_expanded_labels(expanded)

            def restore_expanded(item):
                if self.treeview.item(item, 'text') in expanded_labels:
                    self.treeview.item(item, open=True)
                for child in self.treeview.get_children(item):
                    restore_expanded(child)
            for item in self.treeview.get_children():
                restore_expanded(item)
        # self.clear_tree()
        # self.render_node(self.node_tree)
        # preserve tree state
        expanded_items = set()
        def collect_expanded(item):
            if self.treeview.item(item, 'open'):
                expanded_items.add(item)
            for child in self.treeview.get_children(item):
                collect_expanded(child)
        for item in self.treeview.get_children():
            collect_expanded(item)

        

        def restore_expanded(item):
            if item in expanded_items:
                self.treeview.item(item, open=True)
            for child in self.treeview.get_children(item):
                restore_expanded(child)
        for item in self.treeview.get_children():
            restore_expanded(item)
        if hasattr(self, 'drill_path_stack'):
            current_node, current_path = self.drill_path_stack[-1]
            self.chart_ax.clear()
            self.open_drilldown_chart(current_node, current_path)
        self._refresh_pie_if_open()

    def update_rarity(self, node, rarity):
        node["Rarity"] = rarity
        node_id = ""
        for path, obj in self.tree_paths.items():
            if obj is node:
                node_id = path
                break
        if node_id and node_id in self.node_widgets:
            widget_info = self.node_widgets[node_id]
            rarity_btn = widget_info.get("rarity_widget")
            if rarity_btn:
                cmap = plt.get_cmap('RdYlGn')
                rarity_color_map = {
                    "Abundant": cmap(1.0), "Common": cmap(0.8), "Uncommon": cmap(0.6),
                    "Rare": cmap(0.4), "VeryRare": cmap(0.2), "ExtremelyRare": cmap(0.0)
                }
                rarity_btn.config(
                    text=f"[{rarity} ▼]",
                    bg=self._rgb_to_hex(rarity_color_map.get(rarity, 'white'))
                )
        else:
            expanded_labels = set()
            def collect_expanded(item):
                if self.treeview.item(item, 'open'):
                    expanded_labels.add(self.treeview.item(item, 'text'))
                for child in self.treeview.get_children(item):
                    collect_expanded(child)
            for item in self.treeview.get_children():
                collect_expanded(item)

            self.clear_tree()
            self.render_node(self.node_tree)

            def restore_expanded(item):
                if self.treeview.item(item, 'text') in expanded_labels:
                    self.treeview.item(item, open=True)
                for child in self.treeview.get_children(item):
                    restore_expanded(child)
            for item in self.treeview.get_children():
                restore_expanded(item)
        if hasattr(self, 'drill_path_stack'):
            current_node, current_path = self.drill_path_stack[-1]
            self.chart_ax.clear()
            self.open_drilldown_chart(current_node, current_path)

    def _set_rarity_recursive(self, item, name, new_rarity):
        if self.treeview.item(item, 'text') == name:
            self.treeview.set(item, 'rarity', new_rarity)
        for child in self.treeview.get_children(item):
            self._set_rarity_recursive(child, name, new_rarity)

    def find_node_by_item_id(self, item_id):
        return self.node_widgets.get(item_id)


    def clear_tree(self):
        for item in self.treeview.get_children():
            self.treeview.delete(item)
        self.tree_paths.clear()

# Undo and Redo functions
    def undo_last_change(self):
        if not self.undo_stack:
            messagebox.showinfo("Undo", "No changes to undo.")
            return

        import copy
        self.node_tree = self.undo_stack.pop()

        # Restore the tree
        expanded_labels = set()
        def collect_expanded(item):
            if self.treeview.item(item, 'open'):
                expanded_labels.add(self.treeview.item(item, 'text'))
            for child in self.treeview.get_children(item):
                collect_expanded(child)
        for item in self.treeview.get_children():
            collect_expanded(item)

        self.clear_tree()
        self.render_node(self.node_tree)

        def restore_expanded(item):
            if self.treeview.item(item, 'text') in expanded_labels:
                self.treeview.item(item, open=True)
            for child in self.treeview.get_children(item):
                restore_expanded(child)
        for item in self.treeview.get_children():
            restore_expanded(item)

        # Refresh pie chart if open
        if hasattr(self, 'drill_path_stack'):
            # Try to reopen current chart path or reset to root
            try:
                current_node, current_path = self.drill_path_stack[-1]
                self.chart_ax.clear()
                self.open_drilldown_chart(current_node, current_path)
            except Exception:
                self.drill_path_stack = [(self.node_tree, "ItemLootTreeNodes")]
                self.chart_ax.clear()
                self.open_drilldown_chart(self.node_tree, "ItemLootTreeNodes")

# Loading and Saving
    def load_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not path:
            return

        # Close pie chart if open
        if hasattr(self, 'chart_fig'):
            try:
                plt.close(self.chart_fig)
            except Exception:
                pass
            self.chart_fig = None
            self.chart_ax = None
            self.drill_path_stack = []
            self.drill_entries = []

        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.clear_tree()
            self.node_tree = data
            import copy
            self.original_tree = copy.deepcopy(data)
            import os
            self.loaded_filename = os.path.basename(path)
            self.render_node(data)
            self.current_file_path = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON: {e}")

    def confirm_changes(self):
        import copy

        def walk_tree(node, path=""):
            entries = {}
            full_path = f"{path}.{node['Name']}" if path else node['Name']
            entries[full_path] = node.get("Rarity")
            for child in node.get("Children", []):
                entries.update(walk_tree(child, full_path))
            return entries

        if not hasattr(self, "original_tree"):
            return True  # No original to compare

        original_entries = walk_tree(self.original_tree)
        current_entries = walk_tree(self.node_tree)

        added = []
        removed = []
        modified = []

        for path in current_entries:
            if path not in original_entries:
                added.append(path)
            elif current_entries[path] != original_entries[path]:
                modified.append((path, original_entries[path], current_entries[path]))

        for path in original_entries:
            if path not in current_entries:
                removed.append(path)

        if not added and not removed and not modified:
            return True  # No changes

        summary = ""
        if added:
            summary += "✅ Added:\n" + "\n".join(f"  {a}" for a in added) + "\n\n"
        if removed:
            summary += "❌ Removed:\n" + "\n".join(f"  {r}" for r in removed) + "\n\n"
        if modified:
            summary += "✏️ Modified:\n" + "\n".join(f"  {p} ({old} → {new})" for p, old, new in modified)

        # Scrollable confirmation window
        popup = tk.Toplevel(self)
        popup.title("Review Changes")
        popup.geometry("600x400")
        popup.grab_set()

        decision = {"result": False}

        def confirm():
            decision["result"] = True
            popup.destroy()

        def cancel():
            decision["result"] = False
            popup.destroy()

        # Button frame at the top
        button_frame = tk.Frame(popup)
        button_frame.pack(fill="x", pady=(10, 5))

        tk.Button(button_frame, text="Save Changes", command=confirm).pack(side="left", padx=10)
        tk.Button(button_frame, text="Cancel", command=cancel).pack(side="left", padx=10)

        # Text area below
        text_widget = tk.Text(popup, wrap="word", font=("Courier", 10))
        text_widget.insert("1.0", summary.strip())
        text_widget.config(state="disabled")
        text_widget.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(popup, command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scrollbar.set)


        popup.wait_window()
        return decision["result"]

    def save_json(self):
        if not hasattr(self, 'current_file_path') or not self.current_file_path:
            return self.save_as()  # fallback to Save As

        try:
            if not self.confirm_changes():
                return  # user cancelled
            with open(self.current_file_path, "w") as f:
                json.dump(self.node_tree, f, indent=4)

            messagebox.showinfo("Success", f"Saved to {self.current_file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def save_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        try:
            if not self.confirm_changes():
                return  # user cancelled
            with open(path, "w") as f:
                json.dump(self.node_tree, f, indent=4)

            messagebox.showinfo("Success", f"Exported to {path}")
            self.current_file_path = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export: {e}")

# Renders the Tree View
    def render_node(self, node, indent=0, path="", parent="", group_id=0):
        node_id = path + node["Name"]
        rarity = node.get("Rarity", "")
        postspawn = ", ".join(node.get("PostSpawnActions", []))

        tag = f"group{group_id % 2}"
        item_id = self.treeview.insert(
            parent, "end", text=node["Name"], values=(rarity, postspawn), tags=(tag,)
        )
        self.node_widgets[item_id] = node
        self.tree_paths[node_id] = node

        children = node.get("Children", [])
        for i, child in enumerate(children):
            # If this is a top-level group (child of root), alternate group_id
            next_group_id = group_id
            if parent == "":
                next_group_id = group_id + i
            self.render_node(child, indent + 1, path=node_id + ".", parent=item_id, group_id=next_group_id)

# Add a child
    def add_child_for_node(self, node):
        popup = tk.Toplevel(self)
        popup.title("Add Child Node")
        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        popup.geometry(f"500x300+{x}+{y}")
        popup.grab_set()

        def find_path_for_node(target):
            for path, n in self.tree_paths.items():
                if n is target:
                    return path
            return "(Unknown location)"

        full_path = find_path_for_node(node)

        # Create layout frames
        main_frame = tk.Frame(popup)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left column
        left_frame = tk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky="nw")

        tk.Label(left_frame, text="Parent Node:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(left_frame, text=full_path, wraplength=220, justify="left", fg="blue").grid(row=1, column=0, sticky="w", pady=(0, 10))

        tk.Label(left_frame, text="Child Name:").grid(row=2, column=0, sticky="w")
        name_var = tk.StringVar()
        name_entry = tk.Entry(left_frame, textvariable=name_var, width=30)
        name_entry.grid(row=3, column=0, sticky="w", pady=(0, 10))

        tk.Label(left_frame, text="Rarity:").grid(row=4, column=0, sticky="w")
        rarity_var = tk.StringVar(popup)
        rarity_var.set(RARITIES[0])
        rarity_menu = tk.OptionMenu(left_frame, rarity_var, *RARITIES)
        rarity_menu.grid(row=5, column=0, sticky="w", pady=(0, 10))

        def submit_child():
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showerror("Error", "Child name cannot be empty.")
                return

            import copy
            self.undo_stack.append(copy.deepcopy(self.node_tree))

            new_child = {
                "Name": new_name,
                "Rarity": rarity_var.get(),
                "Children": []
            }

            node.setdefault("Children", []).append(new_child)

            expanded_labels = self._get_expanded_labels()

            self.clear_tree()
            self.render_node(self.node_tree)
            self._restore_expanded_labels(expanded_labels)
            self._refresh_pie_if_open()
            popup.destroy()


        add_button = tk.Button(left_frame, text="Add", command=submit_child)
        add_button.grid(row=6, column=0, sticky="w", pady=(5, 0))

        # Right column (suggestions)
        right_frame = tk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky="n", padx=(20, 0))

        tk.Label(right_frame, text="Suggestions:").pack(anchor="w")
        suggestion_listbox = tk.Listbox(right_frame, height=15, width=25)
        suggestion_listbox.pack()
        suggestion_listbox.pack_forget()  # hide initially

        # Suggestion logic
        def update_suggestions(event=None):
            text = name_var.get().strip().lower()
            matches = [s for s in SUGGESTED_NAMES if text in s.lower()]
            suggestion_listbox.delete(0, tk.END)
            if matches:
                for match in matches[:50]:
                    suggestion_listbox.insert(tk.END, match)
                suggestion_listbox.pack()
            else:
                suggestion_listbox.pack_forget()

        def on_suggestion_select(event):
            if suggestion_listbox.curselection():
                selected = suggestion_listbox.get(suggestion_listbox.curselection()[0])
                name_var.set(selected)
                suggestion_listbox.pack_forget()

        name_entry.bind("<KeyRelease>", update_suggestions)
        suggestion_listbox.bind("<<ListboxSelect>>", on_suggestion_select)

    def add_child(self, index):
        entry = self.drill_entries[index]
        node = entry[2]
        if node is not None:
            self.add_child_for_node(node)

# Remove a node
    def remove_node_for_node(self, node):
        import copy
        self.undo_stack.append(copy.deepcopy(self.node_tree))

        expanded = self._get_expanded_labels()

        def find_and_remove(parent):
            if "Children" in parent:
                for i, child in enumerate(parent["Children"]):
                    if child is node:
                        del parent["Children"][i]
                        return True
                    if find_and_remove(child):
                        return True
            return False

        find_and_remove(self.node_tree)

        # Preserve expanded state
        expanded_labels = set()
        def collect_expanded(item):
            if self.treeview.item(item, 'open'):
                expanded_labels.add(self.treeview.item(item, 'text'))
            for child in self.treeview.get_children(item):
                collect_expanded(child)
        for item in self.treeview.get_children():
            collect_expanded(item)

        self.clear_tree()
        self.node_widgets = {}
        self.render_node(self.node_tree)
        self._restore_expanded_labels(expanded)

        def restore_expanded(item):
            if self.treeview.item(item, 'text') in expanded_labels:
                self.treeview.item(item, open=True)
            for child in self.treeview.get_children(item):
                restore_expanded(child)
        for item in self.treeview.get_children():
            restore_expanded(item)

        if hasattr(self, 'drill_path_stack'):
            current_node, current_path = self.drill_path_stack[-1]
            self.chart_ax.clear()
            self.open_drilldown_chart(current_node, current_path)

    def remove_node(self, index):
        entry = self.drill_entries[index]
        node = entry[2]
        if node is not None:
            self.remove_node_for_node(node)

# Colours
    def _rgb_to_hex(self, rgb):
        r, g, b = [int(255 * x) for x in rgb[:3]]
        return f'#{r:02x}{g:02x}{b:02x}'


if __name__ == "__main__":
    app = NodeTreeApp()
    app.mainloop()
