import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils
import blf

# Store the line coordinates and lengths globally
lines = []  # This will hold pairs of (start, end) points for each line
line_vertex_refs = []  # This will hold references to vertices (object, vertex index) for dynamic updates

line_dynamic_flags = []  # This holds dynamic flags for each line's start and endpoint
font_info = {"font_id": 0, "handler": None}
first_line_drawn = False  # Flag to indicate if at least one line has been drawn
lines_visible = True  # Control whether lines are visible or hidden
drawing_active = False  # Flag to track if the draw operator is active
hovered_vertex = None  # Store the currently hovered vertex
# The distance threshold for highlighting a vertex
vertex_highlight_threshold = 0.05  # Adjust this threshold as needed
edge_highlight_threshold = 5
length_draw_handler = None


# Shader and batch for drawing the lines
shader = gpu.shader.from_builtin('UNIFORM_COLOR')
highlight_shader = gpu.shader.from_builtin('UNIFORM_COLOR')  # Shader for the hovered vertex




# Define a font size property in the Scene
bpy.types.Scene.font_size = bpy.props.FloatProperty(
    name="Font Size",
    description="Adjust the font size for line measurements",
    default=20.0,
    min=10.0,
    max=50.0
)
# Global variable to store the currently hovered edge
hovered_edge = None

def update_hovered_edge(context, event):
    global hovered_edge
    hovered_edge = None  # Reset hovered edge at the beginning
    #print("update_hovered_edge: Reset hovered_edge to None")

    # Get the depsgraph
    depsgraph = context.evaluated_depsgraph_get()
    depsgraph.update()

    best_dist_edge = float('inf')
    region = context.region
    region_3d = context.space_data.region_3d
    mouse_coord = Vector((event.mouse_region_x, event.mouse_region_y))

    for obj in context.visible_objects:
        if obj.type == 'MESH':
            eval_obj = obj.evaluated_get(depsgraph)
            matrix = eval_obj.matrix_world

            for edge in eval_obj.data.edges:
                vert1_world = matrix @ eval_obj.data.vertices[edge.vertices[0]].co
                vert2_world = matrix @ eval_obj.data.vertices[edge.vertices[1]].co

                vert1_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, vert1_world)
                vert2_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, vert2_world)

                if vert1_2d is None or vert2_2d is None:
                    continue  # Skip if projection fails

                edge_2d_vector = vert2_2d - vert1_2d
                edge_length_2d = edge_2d_vector.length
                edge_2d_vector.normalize()

                mouse_to_vert1_2d = mouse_coord - vert1_2d
                t = mouse_to_vert1_2d.dot(edge_2d_vector) / edge_length_2d
                t = max(0.0, min(1.0, t))

                closest_point_2d = vert1_2d + t * edge_2d_vector * edge_length_2d
                dist_2d = (mouse_coord - closest_point_2d).length

                if dist_2d < edge_highlight_threshold and dist_2d < best_dist_edge:
                    closest_point_3d = vert1_world + t * (vert2_world - vert1_world)
                    best_dist_edge = dist_2d
                    hovered_edge = closest_point_3d
               #     print("update_hovered_edge: Edge within range, setting hovered_edge.")

   # if not hovered_edge:
    #    print("update_hovered_edge: Edge snapping stopped, hovered_edge is None.")










            
            
def update_hovered_vertex(context, event):
    global hovered_vertex

    depsgraph = context.evaluated_depsgraph_get()
    depsgraph.update()

    hovered_vertex = None  # Reset hovered vertex initially
    best_dist = float('inf')
    region = context.region
    region_3d = context.space_data.region_3d
    coord = (event.mouse_region_x, event.mouse_region_y)

    # Iterate over all visible objects
    for obj in context.visible_objects:
        if obj.type == 'MESH':
            eval_obj = obj.evaluated_get(depsgraph)
            matrix = eval_obj.matrix_world
            for v in eval_obj.data.vertices:
                world_pos = matrix @ v.co
                screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, world_pos)
                if screen_pos:
                    dist = (Vector(coord) - screen_pos).length
                    if dist < vertex_highlight_threshold and dist < best_dist:
                        best_dist = dist
                        hovered_vertex = world_pos

    # Force redraw after updating hovered vertex
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

# Function to check if the mouse is close to a vertex
def is_mouse_near_vertex(mouse_2d, vertex_world_pos, context):
    region = context.region
    region_3d = context.space_data.region_3d
    vertex_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, vertex_world_pos)
    if vertex_2d is None:
        return False
    distance = (mouse_2d - vertex_2d).length
    return distance < vertex_highlight_threshold

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


# Drawing the lines and hovered vertex in the viewport
def draw():
    if lines_visible and lines:  # Only draw lines if they are visible
        for line in lines:
            start, end = line
            draw_dashed_line(start, end, dash_length=0.5)

    # Draw the hovered vertex if there is one
    if hovered_vertex:
        square_size = 8  # Adjust this value based on screen pixels rather than 3D space
        region = bpy.context.region
        region_3d = bpy.context.space_data.region_3d

        # Project the hovered vertex to 2D screen space
        screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, hovered_vertex)

        if screen_pos:
            square_2d_points = [
                (screen_pos[0] - square_size, screen_pos[1] - square_size),
                (screen_pos[0] + square_size, screen_pos[1] - square_size),
                (screen_pos[0] + square_size, screen_pos[1] + square_size),
                (screen_pos[0] - square_size, screen_pos[1] + square_size)
            ]

            square_3d_points = [
                view3d_utils.region_2d_to_location_3d(region, region_3d, point, hovered_vertex)
                for point in square_2d_points
            ]

            gpu.state.line_width_set(1.4)  # Set to a larger value for a thicker outline
            outline_batch = batch_for_shader(highlight_shader, 'LINE_LOOP', {"pos": square_3d_points})
            highlight_shader.bind()
            highlight_shader.uniform_float("color", (1, 1, 1, 1))  # White color for outline
            outline_batch.draw(highlight_shader)

    # Draw the hovered edge midpoint if there is one
     # Draw the hovered edge midpoint if there is one and no vertex is hovered
    if hovered_edge and not hovered_vertex:
        #print('edge hovered')
        square_size = 8
        region = bpy.context.region
        region_3d = bpy.context.space_data.region_3d

        # Project the hovered edge point to 2D screen space
        screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, hovered_edge)

        if screen_pos:
            square_2d_points = [
                (screen_pos[0] - square_size, screen_pos[1] - square_size),
                (screen_pos[0] + square_size, screen_pos[1] - square_size),
                (screen_pos[0] + square_size, screen_pos[1] + square_size),
                (screen_pos[0] - square_size, screen_pos[1] + square_size)
            ]

            square_3d_points = [
                view3d_utils.region_2d_to_location_3d(region, region_3d, point, hovered_edge)
                for point in square_2d_points
            ]

            if None not in square_3d_points:
                gpu.state.line_width_set(1.4)
                outline_batch = batch_for_shader(highlight_shader, 'LINE_LOOP', {"pos": square_3d_points})
                highlight_shader.bind()
                highlight_shader.uniform_float("color", (0, 1, 0, 1))  # Green color for edge
                outline_batch.draw(highlight_shader)



def draw_dashed_line(start, end, dash_length=0.5, gap_length=None, thickness=3):
    """Draw a dashed line from start to end with customizable dash, gap lengths, thickness, and a solid endpoint."""
    direction = end - start
    length = direction.length
    direction.normalize()

    # Set default gap_length to be equal to dash_length if not provided
    gap_length = gap_length if gap_length is not None else dash_length
    segment_length = dash_length + gap_length
    num_segments = int(length / segment_length)

    gpu.state.line_width_set(thickness)  # Set line thickness
    
    # Draw dashed segments up to the last full segment
    for i in range(num_segments):
        segment_start = start + direction * (i * segment_length)
        segment_end = segment_start + direction * dash_length

        # Draw each dash segment
        batch = batch_for_shader(shader, 'LINES', {"pos": [segment_start, segment_end]})
        shader.bind()
        shader.uniform_float("color", (1, 1, 0, 1))  # Yellow color
        batch.draw(shader)
    
    # Draw a final segment to the endpoint if the last dash does not reach it
    final_segment_start = start + direction * (num_segments * segment_length)
    if (end - final_segment_start).length > 0:
        batch = batch_for_shader(shader, 'LINES', {"pos": [final_segment_start, end]})
        shader.bind()
        shader.uniform_float("color", (1, 1, 0, 1))  # Yellow color
        batch.draw(shader)
    
    gpu.state.line_width_set(1)  # Reset line thickness after drawing


# Function to draw length text dynamically at the midpoint of each line
# Function to draw length text dynamically at the midpoint of each line
def draw_callback_px(self, context):
    """Draw the text at the midpoint of each line"""
    font_id = font_info["font_id"]
    font_size = context.scene.font_size  # Get font size from the scene property

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
                blf.draw(font_id, f"{round(length, 2)} {unit_label}")

# Handler function to update lines based on vertex movement
def update_lines(scene, depsgraph):
    global lines, line_vertex_refs, line_dynamic_flags
    
    for i, (line, refs, dynamic_flags) in enumerate(zip(lines, line_vertex_refs, line_dynamic_flags)):
        updated_start = line[0]  # Backup start position
        updated_end = line[1]  # Backup end position

        # Update start position if it's marked dynamic
        if refs[0] is not None and dynamic_flags[0]:  # Check dynamic flag for start
            obj, vert_idx = refs[0]
            if obj and vert_idx is not None:
                try:
                    # Get the evaluated version of the object
                    eval_obj = obj.evaluated_get(depsgraph)
                    mesh = eval_obj.to_mesh()

                    if vert_idx < len(mesh.vertices):
                        updated_start = eval_obj.matrix_world @ mesh.vertices[vert_idx].co
                    else:
                        #print(f"Vertex index {vert_idx} out of bounds for start point. Falling back to last known position.")
                        updated_start = line[0]  # Fallback to previous position

                    eval_obj.to_mesh_clear()  # Clear the temporary mesh
                except Exception as e:
                    #print(f"Error updating start vertex for line {i}: {e}")
                    updated_start = line[0]  # Fallback to previous position
        
        # Update end position if it's marked dynamic
        if refs[1] is not None:
            obj, vert_idx = refs[1]
            if dynamic_flags[1]:  # Only update if marked as dynamic
                if obj and vert_idx is not None:
                    try:
                        # Get the evaluated version of the object
                        eval_obj = obj.evaluated_get(depsgraph)
                        mesh = eval_obj.to_mesh()

                        if vert_idx < len(mesh.vertices):
                            updated_end = eval_obj.matrix_world @ mesh.vertices[vert_idx].co
                        else:
                           # print(f"Vertex index {vert_idx} out of bounds for end point. Falling back to last known position.")
                            updated_end = line[1]  # Fallback to previous position

                        eval_obj.to_mesh_clear()  # Clear the temporary mesh
                    except Exception as e:
                       # print(f"Error updating end vertex for line {i}: {e}")
                        updated_end = line[1]  # Fallback to previous position

        # Apply the updated start and end positions to the line
        lines[i] = (updated_start, updated_end)

    # Force viewport update
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
        
        if event.type == 'X' and event.value == 'PRESS':
            self.axis_lock['X'] = True
        elif event.type == 'X' and event.value == 'RELEASE':
            self.axis_lock['X'] = False

        if event.type == 'Y' and event.value == 'PRESS':
            self.axis_lock['Y'] = True
        elif event.type == 'Y' and event.value == 'RELEASE':
            self.axis_lock['Y'] = False

        if event.type == 'Z' and event.value == 'PRESS':
            self.axis_lock['Z'] = True
        elif event.type == 'Z' and event.value == 'RELEASE':
            self.axis_lock['Z'] = False

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

                    # The distance threshold for highlighting a vertex
                    vertex_highlight_threshold = 20  # Set to 1.0 to highlight the vertex only within this distance
                    edge_highlight_threshold = 20  # Distance threshold for edge highlighting

                    # Function to check if the mouse is close to a vertex
                    def is_mouse_near_vertex(mouse_2d, vertex_world_pos, context):
                        region = context.region
                        region_3d = context.space_data.region_3d
                        vertex_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, vertex_world_pos)
                        if vertex_2d is None:
                            return False
                        distance = (mouse_2d - vertex_2d).length
                        return distance < vertex_highlight_threshold
                    
                    # Function to check if the mouse is close to an edge
                    def is_mouse_near_edge(mouse_2d, edge_world_pos, context):
                        region = context.region
                        region_3d = context.space_data.region_3d
                        edge_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, edge_world_pos)
                        if edge_2d is None:
                            return False
                        distance = (mouse_2d - edge_2d).length
                        return distance < edge_highlight_threshold

                    if event.type == 'MOUSEMOVE':
                        update_hovered_vertex(context, event)
                        update_hovered_edge(context, event)
                      #  if hovered_edge is None:
                        #    print("modal: Confirming no edge in range; resetting hovered_edge to None.")
                       # if hovered_vertex is None:
                         #   print("modal: Confirming no vertex in range; resetting hovered_vertex to None.")
                        depsgraph = context.evaluated_depsgraph_get()
                        depsgraph.update()


                        best_dist = float('inf')
                        best_dist_edge = float('inf')

                        region = context.region
                        region_3d = context.space_data.region_3d
                        coord = (event.mouse_region_x, event.mouse_region_y)

                        # Get a base 3D position under the mouse without snapping
                        base_pos = view3d_utils.region_2d_to_location_3d(region, region_3d, coord, context.space_data.region_3d.view_location)

                        # Iterate over all objects in the scene
                        for obj in context.visible_objects:
                            if obj.type == 'MESH':
                                matrix = obj.matrix_world

                                # Check vertices for proximity
                                for v in obj.data.vertices:
                                    world_pos = matrix @ v.co
                                    screen_pos = view3d_utils.location_3d_to_region_2d(region, region_3d, world_pos)
                                    if screen_pos:
                                        dist = (Vector(coord) - screen_pos).length
                                        if dist < vertex_highlight_threshold and dist < best_dist:
                                            best_dist = dist
                                            hovered_vertex = world_pos
                                            self.hovered_vertex_ref = (obj, v.index)

                                # Check edges only if no vertex is close enough
                                if not hovered_vertex:
                                    for edge in obj.data.edges:
                                        vert1_world = matrix @ obj.data.vertices[edge.vertices[0]].co
                                        vert2_world = matrix @ obj.data.vertices[edge.vertices[1]].co
                                        edge_vector = vert2_world - vert1_world
                                        edge_length = edge_vector.length
                                        edge_vector.normalize()

                                        mouse_3d = view3d_utils.region_2d_to_location_3d(region, region_3d, coord, vert1_world)
                                        proj_vector = mouse_3d - vert1_world
                                        t = proj_vector.dot(edge_vector) / edge_length
                                        t = max(0.0, min(1.0, t))

                                        closest_point = vert1_world + t * edge_vector * edge_length

                                        screen_pos_edge = view3d_utils.location_3d_to_region_2d(region, region_3d, closest_point)
                                        if screen_pos_edge:
                                            dist = (Vector(coord) - screen_pos_edge).length
                                            if dist < edge_highlight_threshold and dist < best_dist_edge:
                                                best_dist_edge = dist
                                                hovered_edge = closest_point
                                                self.hovered_edge_ref = (obj, edge.index)
                                                

                        # Start with the base position under the mouse, and apply snapping conditionally
                        if self.start_pos is not None:
                            current_pos = mouse_to_3d(context, event, self.start_pos)

                            #print(hovered_edge)
                            if hovered_vertex:
                                if not any(self.axis_lock.values()):

                                    current_pos = hovered_vertex
                                    print("modal: Snapping to vertex.")
                                else:
                                    # Snap to the hovered vertex's coordinates, respecting locked axes
                                    if self.axis_lock['X']:
                                        current_pos[0] = hovered_vertex[0]  # Keep X axis locked
                                    if self.axis_lock['Y']:
                                        current_pos[1] = hovered_vertex[1]  # Keep Y axis locked
                                    if self.axis_lock['Z']:
                                        current_pos[2] = hovered_vertex[2]  # Keep Z axis locked
                                
                            elif hovered_edge:
                                if not any(self.axis_lock.values()):
                                    current_pos = hovered_edge
                                    print("modal: Snapping to edge.")
                                    print(current_pos)
                                else:
                                    # Snap to the hovered vertex's coordinates, respecting locked axes
                                    if self.axis_lock['X']:
                                        current_pos[0] = hovered_edge[0]  # Keep X axis locked
                                    if self.axis_lock['Y']:
                                        current_pos[1] = hovered_edge[1]  # Keep Y axis locked
                                    if self.axis_lock['Z']:
                                        current_pos[2] = hovered_edge[2]  # Keep Z axis locked

                            # Apply axis locking
                            if self.axis_lock['X']:
                                current_pos[1] = self.start_pos[1]
                                current_pos[2] = self.start_pos[2]
                            if self.axis_lock['Y']:
                                current_pos[0] = self.start_pos[0]
                                current_pos[2] = self.start_pos[2]
                            if self.axis_lock['Z']:
                                current_pos[0] = self.start_pos[0]
                                current_pos[1] = self.start_pos[1]

                            # Ensure a line exists before updating
                            if lines:
                                lines[-1][1] = current_pos
                                self.current_pos = current_pos
                                context.area.tag_redraw()





                    elif event.type == 'LEFTMOUSE':
                        if event.value == 'PRESS':
                            # Set the start position based on hovered vertex or edge
                            if hovered_vertex:
                                self.start_hovered_vertex = hovered_vertex
                                self.start_pos = hovered_vertex
                                self.start_vertex_ref = self.hovered_vertex_ref  # Store reference to the vertex
                               # print(f"Start position set to hovered vertex: {self.start_pos}")
                            elif hovered_edge:
                                self.start_pos = hovered_edge  # Snap to the closest point on the edge
                                self.start_hovered_vertex = None
                                self.start_vertex_ref = self.hovered_edge_ref  # Store reference to the edge
                               # print(f"Start position set to hovered edge: {self.start_pos}")
                            else:
                                # Fallback to the 3D mouse location if no vertex or edge is hovered
                                self.start_pos = mouse_to_3d(context, event, Vector((0, 0, 0)))
                                self.start_hovered_vertex = None
                                self.start_vertex_ref = None
                              #  print(f"Start position set to mouse 3D location: {self.start_pos}")

                            # Start a new line with the initial start position
                            lines.append([self.start_pos.copy(), self.start_pos.copy()])
                            line_vertex_refs.append([self.start_vertex_ref, None])
                        elif event.value == 'RELEASE':
                            final_position = self.current_pos if self.current_pos else mouse_to_3d(context, event, self.start_pos)
                            lines[-1][1] = final_position  # Set final position of the line

                            # Clear hovered vertex after setting the final position
                            current_hovered_vertex = hovered_vertex
                            hovered_vertex = None  # Clear it explicitly here
                           # print(f"Hovered vertex cleared on release.")

                            # Determine if the start position should be dynamic with a tolerance check
                            if self.start_hovered_vertex and (self.start_pos - self.start_hovered_vertex).length < 1e-6:
                                line_vertex_refs[-1][0] = self.start_vertex_ref
                                start_dynamic = True
                           #     print(f"Start position set to dynamic: {self.start_pos}")
                            else:
                                line_vertex_refs[-1][0] = None
                                start_dynamic = False
                             #   print(f"Start position set to static: {self.start_pos}")

                            # Determine if the endpoint should be dynamic by checking closeness
                            if current_hovered_vertex and (final_position - current_hovered_vertex).length < 1e-6:
                                line_vertex_refs[-1][1] = self.hovered_vertex_ref
                                obj, vert_idx = self.hovered_vertex_ref
                                end_dynamic = True
                              #  print(f"Endpoint set to dynamic: final_position {final_position} matches hovered_vertex {current_hovered_vertex}, vert_idx {vert_idx}")
                            else:
                                # Store the endpoint’s static position if it's not dynamic
                                line_vertex_refs[-1][1] = (None, final_position)
                                end_dynamic = False
                              #  print(f"Endpoint set to static: final_position {final_position} does not match hovered_vertex {current_hovered_vertex}")

                            # Append dynamic flags for this line
                            line_dynamic_flags.append([start_dynamic, end_dynamic])
                          #  print(f"Dynamic flags for line {len(lines)}: {line_dynamic_flags[-1]}")

                            # Reset for the next line
                            self.start_pos = None
                            self.start_vertex_ref = None
                            self.current_pos = None







                    elif event.type in {'RIGHTMOUSE', 'ESC'}:
                        self.cancel(context)
                        return {'CANCELLED'}

                    elif event.type == 'RET':
                        self.cancel(context)
                        return {'FINISHED'}

                break  # Exit the area loop as we have already processed the VIEW_3D area
            if event.type == 'X':
                if event.value == 'PRESS':
                    self.restrict_axis = 'X'
            elif event.type == 'Y':
                if event.value == 'PRESS':
                    self.restrict_axis = 'Y'
            elif event.type == 'Z':
                if event.value == 'PRESS':
                    self.restrict_axis = 'Z'
            elif event.type in {'X', 'Y', 'Z'} and event.value == 'RELEASE':
                self.restrict_axis = None

            if context.area:
                context.area.tag_redraw()

        # If the mouse is in an unrecognized area (like top menu), cancel the operation
        if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MOUSEMOVE'} and not mouse_in_known_area and event.value == 'PRESS':
            self.cancel(context)
            #print('Pressed in top menu')
            return {'PASS_THROUGH'}

        # Allow view panning with the middle mouse button in VIEW_3D
        if event.type == 'MIDDLEMOUSE':
            return {'PASS_THROUGH'}

        # Allow zooming with mouse wheel or trackpad in VIEW_3D
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
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
        
        for index, line in enumerate(lines):
            row = layout.row()
            start, end = line
            row.label(text=f"Line {index + 1}: Start: {start}, End: {end}")
            row.operator("view3d.delete_line", text="Delete").index = index

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
# Register the depsgraph update handler
def register_depsgraph_handler():
    if update_lines not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(update_lines)

# Unregister the depsgraph update handler
def unregister_depsgraph_handler():
    if update_lines in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(update_lines)

# List of classes for registration
classes = [
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

def unregister():
    unregister_depsgraph_handler()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.font_size    


if __name__ == "__main__":
    register()