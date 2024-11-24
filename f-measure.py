import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils
import blf
import mathutils
import bmesh
from mathutils.bvhtree import BVHTree

line_colors = []  # This will store colors for each line
# Store the line coordinates and lengths globally
lines = []  # This will hold pairs of (start, end) points for each line
line_vertex_refs = []  # This will hold references to vertices (object, vertex index) for dynamic updates
line_dynamic_flags = []  # This holds dynamic flags for each line's start and endpoint
line_colors = []  # This will hold the colors for each line
font_info = {"font_id": 0, "handler": None}
first_line_drawn = False  # Flag to indicate if at least one line has been drawn
lines_visible = True  # Control whether lines are visible or hidden
drawing_active = False  # Flag to track if the draw operator is active
hovered_vertex = None  # Store the currently hovered vertex
hovered_edge = None  # Store the currently hovered edge
vertex_highlight_threshold = 10  # Adjust this threshold as needed
edge_highlight_threshold = 1
length_draw_handler = None

# Shader and batch for drawing the lines
shader = gpu.shader.from_builtin('UNIFORM_COLOR')
highlight_shader = gpu.shader.from_builtin('UNIFORM_COLOR')  # Shader for the hovered vertex

bpy.types.Scene.font_size = bpy.props.FloatProperty(
    name="Font Size",
    description="Adjust the font size for line measurements",
    default=20.0,
    min=10.0,
    max=50.0
)

# Cache to store BVH trees per object
bvh_cache = {}

def add_line_color(index):
    def update_color(self, context):
        line_colors[index] = getattr(context.scene, f"line_color_{index}")
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    color_property_name = f"line_color_{index}"

    # Check if the property already exists in the scene
    if hasattr(bpy.types.Scene, color_property_name):
        # Reset the property to the default value if it exists
        setattr(bpy.context.scene, color_property_name, (1.0, 1.0, 0.0, 1.0))  # Default yellow color
    else:
        # Create a new property if it doesn't exist
        setattr(bpy.types.Scene, color_property_name, bpy.props.FloatVectorProperty(
            name=f"Line {index} Color",
            subtype='COLOR',
            size=4,
            min=0.0, max=1.0,
            default=(1.0, 1.0, 0.0, 1.0),  # Default yellow color
            update=update_color  # Use callback for updates
        ))

    # Add the default color to the line_colors list
    line_colors.append((1.0, 1.0, 0.0, 1.0))


def build_bvh(obj):
    """Build and cache a BVH tree for the given object."""
    if obj.type != 'MESH':
        return None

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()

    # Create BVH tree from the evaluated mesh
    bvh_tree = BVHTree.FromObject(eval_obj, depsgraph)
    eval_obj.to_mesh_clear()  # Clean up temporary mesh
    return bvh_tree


def get_bvh(obj):
    """Get or build a BVH tree for the given object."""
    if obj not in bvh_cache or bvh_cache[obj]["dirty"]:
        bvh_tree = build_bvh(obj)
        if bvh_tree:
            bvh_cache[obj] = {"bvh": bvh_tree, "dirty": False}
    return bvh_cache[obj]["bvh"]


def mark_bvh_dirty(obj):
    """Mark BVH tree as dirty if the object is modified."""
    if obj in bvh_cache:
        bvh_cache[obj]["dirty"] = True


def update_hovered_geometry(context, event):
    """Efficiently update hovered vertex or edge based on the mouse position."""
    hovered_vertex = None
    hovered_vertex_ref = None
    hovered_edge = None
    hovered_edge_ref = None

    best_vertex_dist = float('inf')
    best_edge_dist = float('inf')

    region = context.region
    region_3d = context.space_data.region_3d
    mouse_coord = Vector((event.mouse_region_x, event.mouse_region_y))

    # Precompute ray origin and direction
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, mouse_coord)
    ray_direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, mouse_coord)

    for obj in context.visible_objects:
        if obj.type != 'MESH':
            continue

        matrix_world = obj.matrix_world
        bvh_tree = get_bvh(obj)
        if not bvh_tree:
            continue

        # Perform raycast using BVH tree
        raycast_result = bvh_tree.ray_cast(ray_origin, ray_direction)
        if raycast_result[0] is not None:  # If a hit is found
            location, normal, face_index, dist = raycast_result

            # Check closest vertex
            for vertex in obj.data.vertices:
                world_pos = matrix_world @ vertex.co
                screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, world_pos)
                if screen_pos:
                    vertex_dist = (mouse_coord - screen_pos).length
                    if vertex_dist < vertex_highlight_threshold and vertex_dist < best_vertex_dist:
                        best_vertex_dist = vertex_dist
                        hovered_vertex = world_pos
                        hovered_vertex_ref = (obj, vertex.index)

            # Check closest edge using the face index from raycast
            if face_index is not None:
                face = obj.data.polygons[face_index]
                for loop_index in face.loop_indices:
                    edge_index = obj.data.loops[loop_index].edge_index
                    edge = obj.data.edges[edge_index]

                    vert1_world = matrix_world @ obj.data.vertices[edge.vertices[0]].co
                    vert2_world = matrix_world @ obj.data.vertices[edge.vertices[1]].co

                    # Find closest point on the edge
                    closest_point, _ = mathutils.geometry.intersect_point_line(location, vert1_world, vert2_world)
                    edge_dist = (location - closest_point).length
                    if edge_dist < edge_highlight_threshold and edge_dist < best_edge_dist:
                        best_edge_dist = edge_dist
                        hovered_edge = closest_point
                        hovered_edge_ref = (obj, edge_index)  # Store the edge index correctly

    return hovered_vertex, hovered_vertex_ref, hovered_edge, hovered_edge_ref


            
# Function to convert 2D mouse coordinates into 3D space (using a depth reference point)
def mouse_to_3d(context, event, depth_location):
    region = context.region
    region_3d = context.space_data.region_3d
    mouse_coord = (event.mouse_region_x, event.mouse_region_y)
    return view3d_utils.region_2d_to_location_3d(region, region_3d, mouse_coord, depth_location)

# Function to calculate the length of a line segment
def calculate_length(start, end):
    return (end - start).length

# Drawing the lines and hovered vertex in the viewport
import math

import time
last_update_time = 0
update_interval = 0.02  # Limit updates to every 20ms

def should_update_highlight():
    global last_update_time
    current_time = time.time()
    if current_time - last_update_time > update_interval:
        last_update_time = current_time
        return True
    return False
# Drawing the lines and hovered vertex in the viewport
def draw():
    def draw_square_around_point(screen_pos, reference_3d_point, color, square_size=8):
        """Draws a square around a 3D point projected to 2D."""
        region = bpy.context.region
        region_3d = bpy.context.space_data.region_3d

        # Create 2D points for the square
        square_2d_points = [
            (screen_pos[0] - square_size, screen_pos[1] - square_size),
            (screen_pos[0] + square_size, screen_pos[1] - square_size),
            (screen_pos[0] + square_size, screen_pos[1] + square_size),
            (screen_pos[0] - square_size, screen_pos[1] + square_size)
        ]

        # Convert 2D points back to 3D using the reference point for depth
        square_3d_points = [
            view3d_utils.region_2d_to_location_3d(region, region_3d, point, reference_3d_point)
            for point in square_2d_points
        ]

        # Check if points are valid
        if None not in square_3d_points:
            gpu.state.line_width_set(1.4)
            outline_batch = batch_for_shader(
                highlight_shader, 'LINE_LOOP', {"pos": square_3d_points}
            )
            highlight_shader.bind()
            highlight_shader.uniform_float("color", color)
            outline_batch.draw(highlight_shader)

    if lines_visible and lines:  # Only draw lines if they are visible
        for index, line in enumerate(lines):
            start, end = line
            draw_dashed_line(start, end, dash_length=0.5, index=index)

    # Draw hovered vertex
    if hovered_vertex:
        region = bpy.context.region
        region_3d = bpy.context.space_data.region_3d
        screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, hovered_vertex)
        if screen_pos:
            draw_square_around_point(screen_pos, hovered_vertex, color=(1, 1, 1, 1))  # White

    # Draw hovered edge midpoint if no vertex is hovered
    if hovered_edge and not hovered_vertex:
        region = bpy.context.region
        region_3d = bpy.context.space_data.region_3d
        screen_pos_edge = view3d_utils.location_3d_to_region_2d(region, region_3d, hovered_edge)
        if screen_pos_edge:
            draw_square_around_point(screen_pos_edge, hovered_edge, color=(0, 1, 0, 1))  # Green


# Function to draw dashed lines with specific colors
def draw_dashed_line(start, end, dash_length=0.5, gap_length=None, thickness=3, index=None):
    direction = end - start
    length = direction.length
    direction.normalize()

    # Set default gap_length to be equal to dash_length if not provided
    gap_length = gap_length if gap_length is not None else dash_length
    segment_length = dash_length + gap_length

    gpu.state.line_width_set(thickness)  # Set line thickness

    # Use the color assigned to the line
    color = line_colors[index] if index is not None and index < len(line_colors) else (1.0, 1.0, 0.0, 1.0)
    batch = batch_for_shader(shader, 'LINES', {"pos": [start, end]})
    shader.bind()
    shader.uniform_float("color", color)  # Dynamic color
    batch.draw(shader)

    gpu.state.line_width_set(1)  # Reset line thickness after drawing




# Function to draw length text dynamically at the midpoint of each line
def draw_callback_px(self, context):
    """Draw the text at the midpoint of each line"""
    font_id = font_info["font_id"]
    font_size = context.scene.font_size  # Get font size from the scene property
    decimals = context.scene.length_decimals  # Get the number of decimals to display

    # Retrieve the scene unit scale and unit name
    unit_settings = context.scene.unit_settings
    scale_length = unit_settings.scale_length
    unit_name = unit_settings.length_unit  # 'METERS', 'CENTIMETERS', etc.

    # Map Blender's unit names to display-friendly names
    unit_map = {
        'METERS': 'm',
        'CENTIMETERS': 'cm',
        'MILLIMETERS': 'mm',
        'KILOMETERS': 'km',
        'INCHES': 'in',
        'FEET': 'ft',
        'MILES': 'mi',
        'NONE': ''  # If no units are set, use an empty string
    }
    unit_label = unit_map.get(unit_name, '')

    if lines_visible:  # Only draw lengths if they are visible
        for line in lines:
            start, end = line
            length = calculate_length(start, end)  # Calculate length of the current line

            # Calculate the midpoint of the line
            midpoint = (start + end) / 2

            # Convert 3D midpoint to 2D screen space
            region = context.region
            region_3d = context.space_data.region_3d
            mid_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, midpoint)

            # Draw the length at the midpoint if the midpoint is visible
            if mid_2d:
                blf.color(font_id, 1.0, 1.0, 1.0, 1.0)  # RGBA for white color
                
                # Set the font size and position for the length text
                blf.position(font_id, mid_2d[0], mid_2d[1], 0)
                blf.size(font_id, int(font_size))  # Use the custom font size
                blf.draw(font_id, f"{length:.{decimals}f} {unit_label}")


# Handler function to update lines based on vertex movement
def update_lines(scene, depsgraph):
    global lines, line_vertex_refs, line_dynamic_flags

    # Cache evaluated objects and meshes
    evaluated_objects = {}
    meshes = {}

    for obj in bpy.context.visible_objects:
        if obj.type == 'MESH':
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            evaluated_objects[obj] = eval_obj
            meshes[obj] = mesh

    # Update line positions
    for i, (line, refs, dynamic_flags) in enumerate(zip(lines, line_vertex_refs, line_dynamic_flags)):
        updated_start = line[0]
        updated_end = line[1]
        print(f"Line {i}: Start ref: {refs[0]}, End ref: {refs[1]}, Dynamic flags: {dynamic_flags}")

        # Update start position if dynamic
        if refs[0] is not None and dynamic_flags[0]:
            obj, vert_idx = refs[0]
            if obj in meshes and vert_idx is not None:
                updated_start = evaluated_objects[obj].matrix_world @ meshes[obj].vertices[vert_idx].co

        # Update end position if dynamic
        if refs[1] is not None and dynamic_flags[1]:
            obj, vert_idx = refs[1]
            if obj in meshes and vert_idx is not None:
                updated_end = evaluated_objects[obj].matrix_world @ meshes[obj].vertices[vert_idx].co

        # Apply updates
        lines[i] = (updated_start, updated_end)

    # Clear temporary meshes
    for obj, mesh in meshes.items():
        evaluated_objects[obj].to_mesh_clear()

    # Redraw viewport
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()



def init():
    """Initialize font for text drawing"""
    global font_info
    font_info["font_id"] = 0  # Use default Blender font

# Modal operator to handle mouse input and draw lines
class ModalDrawOperator(bpy.types.Operator):
    """Draw a yellow line with the mouse"""
    bl_idname = "view3d.modal_draw"
    bl_label = "Draw measurement Line"
    
    def __init__(self):
        self.start_pos = None
        self.start_vertex_ref = None  # Initialize start_vertex_ref to None
        self.hovered_vertex_ref = None  # Initialize hovered_vertex_ref to None
        self.hovered_edge_ref = None  # Initialize hovered_edge_ref to None
        self.end_pos = None
        self.axis_lock = {'X': False, 'Y': False, 'Z': False}

    def modal(self, context, event):
        global lines, first_line_drawn, drawing_active, hovered_vertex, line_vertex_refs, hovered_edge
        
        # Check if drawing is active; if not, cancel the operation
        if not drawing_active:
            return {'CANCELLED'}
        if event.type == 'N' and event.value == 'PRESS':
            return {'PASS_THROUGH'}

        # Get mouse coordinates and window
        mouse_x, mouse_y = event.mouse_x, event.mouse_y
        window = context.window

        # Track whether the mouse is over a known area
        mouse_in_known_area = False
        
        # Handle axis locking (both PRESS and RELEASE)
        if event.type in {'X', 'Y', 'Z'}:
            self.axis_lock[event.type] = (event.value == 'PRESS')

        # Find the area under the mouse
        for area in window.screen.areas:
            if area.x <= mouse_x <= area.x + area.width and area.y <= mouse_y <= area.y + area.height:
                area_type = area.type
               # print(area_type)  # This will print the type of area the mouse is in

                # If the area is something else (like VIEW_3D), mark it as known
                mouse_in_known_area = True

                # Allow pass-through for non-VIEW_3D areas
                if area_type != 'VIEW_3D':
                    return {'PASS_THROUGH'}

                # Handle mouse movement for drawing lines within VIEW_3D only
                if area_type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'UI':  # N-panel region check
                            if region.x <= mouse_x <= region.x + region.width and region.y <= mouse_y <= region.y + region.height:
                              #  print("Mouse is over the N-panel")
                                return {'PASS_THROUGH'}

                    # Allow zooming with the mouse wheel in VIEW_3D
                    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                        return {'PASS_THROUGH'}


                

                    if event.type == 'MOUSEMOVE' and should_update_highlight():
                        # Update hovered geometry and get results
                        hovered_vertex, hovered_vertex_ref, hovered_edge, hovered_edge_ref = update_hovered_geometry(context, event)

                        # Update references in the class
                        self.hovered_vertex_ref = hovered_vertex_ref
                        self.hovered_edge_ref = hovered_edge_ref

                        # Trigger viewport redraw if necessary
                        if hovered_vertex or hovered_edge:
                            for area in context.screen.areas:
                                if area.type == 'VIEW_3D':
                                    area.tag_redraw()

                        # Update snapping logic based on hovered geometry
                        if self.start_pos is not None:
                            current_pos = mouse_to_3d(context, event, self.start_pos)

                            if hovered_vertex:
                                for axis, locked in self.axis_lock.items():
                                    if locked:
                                        current_pos["XYZ".index(axis)] = hovered_vertex["XYZ".index(axis)]
                                if not any(self.axis_lock.values()):
                                    current_pos = hovered_vertex

                            elif hovered_edge:
                                for axis, locked in self.axis_lock.items():
                                    if locked:
                                        current_pos["XYZ".index(axis)] = hovered_edge["XYZ".index(axis)]
                                if not any(self.axis_lock.values()):
                                    current_pos = hovered_edge


                            # Apply axis locking
                            for axis, locked in self.axis_lock.items():
                                if locked:
                                    for i, coord in enumerate("XYZ"):
                                        if coord != axis:
                                            current_pos[i] = self.start_pos[i]

                            # Update the current line
                            if lines:
                                lines[-1][1] = current_pos
                                self.current_pos = current_pos
                                context.area.tag_redraw()

                    elif event.type == 'LEFTMOUSE':
                        if event.value == 'PRESS':
                            # Set start position and reference based on hover state
                            if hovered_vertex:
                                self.start_pos, self.start_hovered_vertex, self.start_vertex_ref = (
                                    hovered_vertex, hovered_vertex, self.hovered_vertex_ref
                                )
                            elif hovered_edge:
                                self.start_pos, self.start_hovered_vertex, self.start_vertex_ref = (
                                    hovered_edge, None, self.hovered_edge_ref
                                )
                            else:
                                self.start_pos, self.start_hovered_vertex, self.start_vertex_ref = (
                                    mouse_to_3d(context, event, Vector((0, 0, 0))), None, None
                                )

                            # Start a new line
                            lines.append([self.start_pos.copy(), self.start_pos.copy()])
                            line_vertex_refs.append([self.start_vertex_ref, None])
                            add_line_color(len(lines) - 1)

                        elif event.value == 'RELEASE':
                            final_position = self.current_pos or mouse_to_3d(context, event, self.start_pos)
                            lines[-1][1] = final_position

                            # Clear hovered vertex
                            current_hovered_vertex, hovered_vertex = hovered_vertex, None

                            # Determine dynamic or static flags
                            start_dynamic = (
                                self.start_hovered_vertex 
                                and (self.start_pos - self.start_hovered_vertex).length < 1e-6
                            )
                            line_vertex_refs[-1][0] = self.start_vertex_ref if start_dynamic else None

                            end_dynamic = (
                                current_hovered_vertex 
                                and (final_position - current_hovered_vertex).length < 1e-6
                            )
                            line_vertex_refs[-1][1] = (
                                self.hovered_vertex_ref if end_dynamic else (None, final_position)
                            )

                            line_dynamic_flags.append([start_dynamic, end_dynamic])

                            # Reset for the next line
                            self.start_pos, self.start_vertex_ref, self.current_pos = None, None, None

                    elif event.type in {'RIGHTMOUSE', 'ESC'}:
                        self.cancel(context)
                        return {'CANCELLED'}

                    elif event.type == 'RET':
                        self.cancel(context)
                        return {'FINISHED'}

                break  # Exit the area loop as we have already processed the VIEW_3D area
            if event.type in {'X', 'Y', 'Z'}:
              self.restrict_axis = event.type if event.value == 'PRESS' else None
            if context.area:
                context.area.tag_redraw()

        # If the mouse is in an unrecognized area (like top menu), cancel the operation
        if (
            (event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MOUSEMOVE'} and not mouse_in_known_area and event.value == 'PRESS') 
            or event.type == 'MIDDLEMOUSE' 
            or event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
        ):
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MOUSEMOVE'} and not mouse_in_known_area and event.value == 'PRESS':
                self.cancel(context)
            return {'PASS_THROUGH'}

        if context.area:
            context.area.tag_redraw()

        return {'RUNNING_MODAL'}


    def invoke(self, context, event):
        global drawing_active, length_draw_handler

        if drawing_active:
            # If already active, stop the drawing mode
            self.cancel(context)
            return {'CANCELLED'}
        else:
            init()  # Initialize font
            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_VIEW')
            font_info["handler"] = bpy.types.SpaceView3D.draw_handler_add(
                draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL')
            
            # Ensure length draw handler is added only once
            if length_draw_handler is None:
                length_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                    draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL'
                )

            # Force update depsgraph to get the latest mesh info
            depsgraph = context.evaluated_depsgraph_get()
            depsgraph.update()

            # Update mesh data if in Edit mode
            for obj in context.visible_objects:
                if obj.type == 'MESH' and obj.mode == 'EDIT':
                    obj.update_from_editmode()

            context.window_manager.modal_handler_add(self)
            drawing_active = True  # Set this to true when starting to draw
            return {'RUNNING_MODAL'}


    def cancel(self, context):
        global drawing_active, hovered_vertex, hovered_edge
        drawing_active = False
        hovered_vertex = None  # Clear hovered vertex on cancel
        hovered_edge = None  # Clear hovered edge on cancel

        # Only remove the font_info handler for text or highlights
        if font_info["handler"]:
            bpy.types.SpaceView3D.draw_handler_remove(font_info["handler"], 'WINDOW')
            font_info["handler"] = None

        # Do not remove `self._handle` to preserve line rendering
        # This ensures lines persist in the viewport

        # Ensure the viewport redraws
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'CANCELLED'}




def get_font_size():
    return bpy.context.scene.get("font_size", 20)

def set_font_size(value):
    bpy.context.scene["font_size"] = value

bpy.types.Scene.font_size = property(get_font_size, set_font_size)

# Update the panel class to include the font size control
# Update the panel class to include a color picker for each line
class VIEW3D_PT_draw_line_panel(bpy.types.Panel):
    bl_label = "Draw Measurement Line"
    bl_idname = "VIEW3D_PT_draw_line_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        if drawing_active:
            layout.operator("view3d.modal_draw", text="Drawing Line... (Click to Stop)")
        else:
            layout.operator("view3d.modal_draw", text="Draw Measurement Line")

        toggle_text = "Hide Lines & Lengths" if lines_visible else "Show Lines & Lengths"
        layout.operator("view3d.toggle_lines_visibility", text=toggle_text)
        
        # Font size control
        layout.prop(context.scene, "font_size", text="Font Size")
        
        # Decimal places control
        layout.prop(context.scene, "length_decimals", text="Decimal Places")
        
        for index, line in enumerate(lines):
            row = layout.row()
            start, end = line
            row.label(text=f"Line {index + 1}: Start: {start}, End: {end}")
            row.operator("view3d.delete_line", text="Delete").index = index

            # Add a color picker for the line
            color_row = layout.row()
            color_row.prop(context.scene, f"line_color_{index}", text="Line Color")


class DeleteLineOperator(bpy.types.Operator):
    bl_idname = "view3d.delete_line"
    bl_label = "Delete Line"

    index: bpy.props.IntProperty()

    def execute(self, context):
        global lines, line_vertex_refs, line_dynamic_flags
        # Check if the index is within the bounds of the list
        if 0 <= self.index < len(lines):
            # Delete the line, vertex reference, and dynamic flags at the specified index
            lines.pop(self.index)
            line_colors.pop(self.index)
            line_vertex_refs.pop(self.index)
            line_dynamic_flags.pop(self.index)
            context.area.tag_redraw()
        else:
            self.report({'WARNING'}, "Index out of bounds or list is empty")
        return {'FINISHED'}



class ToggleLinesVisibilityOperator(bpy.types.Operator):
    bl_idname = "view3d.toggle_lines_visibility"
    bl_label = "Toggle Lines Visibility"

    def execute(self, context):
        global lines_visible, drawing_active
        lines_visible = not lines_visible  
        if not lines_visible and drawing_active:
            drawing_active = False
            if font_info["handler"]:
                bpy.types.SpaceView3D.draw_handler_remove(font_info["handler"], 'WINDOW')
                font_info["handler"] = None
        context.area.tag_redraw()
        return {'FINISHED'}
# Monitor for mesh changes to invalidate the BVH cache
@bpy.app.handlers.persistent
def depsgraph_update(scene, depsgraph):
    # Call mark_bvh_dirty for updated mesh objects
    for update in depsgraph.updates:
        obj = update.id
        if isinstance(obj, bpy.types.Object) and obj.type == 'MESH':
            mark_bvh_dirty(obj)
    
    # Call update_lines to handle dynamic line updates
    update_lines(scene, depsgraph)



# Register the depsgraph update handler
def register_depsgraph_handler():
    if depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_update)


def unregister_depsgraph_handler():
    if depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update)


# List of classes for registration
classes = [
    # Replace with your operator and panel classes
    # Example:
     ModalDrawOperator,
     VIEW3D_PT_draw_line_panel,
     ToggleLinesVisibilityOperator,
     DeleteLineOperator,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_depsgraph_handler()
    bpy.types.Scene.font_size = bpy.props.FloatProperty(
        name="Font Size",
        description="Adjust the font size for line measurements",
        default=20.0,
        min=10.0,
        max=50.0
    )
    bpy.types.Scene.length_decimals = bpy.props.IntProperty(
        name="Decimal Places",
        description="Number of decimal places to display for line lengths",
        default=2,
        min=0,
        max=10
    )

    # Dynamically add color properties for each line
    for i in range(len(lines)):
        prop_name = f"line_color_{i}"
        setattr(bpy.types.Scene, prop_name, bpy.props.FloatVectorProperty(
            name=f"Line {i + 1} Color",
            subtype='COLOR',
            size=4,
            default=(1.0, 1.0, 0.0, 1.0),  # Default to yellow
            min=0.0,
            max=1.0
        ))
        line_colors.append((1.0, 1.0, 0.0, 1.0))  # Default color for each line

def unregister():
    unregister_depsgraph_handler()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.font_size
    del bpy.types.Scene.length_decimals

    # Dynamically remove color properties for each line
    for i in range(len(lines)):
        prop_name = f"line_color_{i}"
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)

if __name__ == "__main__":
    register()
