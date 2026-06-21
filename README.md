<<<<<<< HEAD
# Self-Balancing Two-Wheeled Robot — ROS 2 Humble + Gazebo Classic 11

## 1. STL analysis (how each part was identified)

The uploaded zip contained 6 STL files with corrupted/non-descriptive
filenames (`Pièce1.STL` etc., mangled to `Pi#U00e8ce1.STL`). Filenames were
**not trusted**. Each file was parsed directly (binary STL triangle data,
bounding box, signed volume, fill ratio) and rendered from three angles to
determine its actual role:

| File (as uploaded)        | Renamed mesh         | Dimensions (mm) | Fill ratio | Identified role |
|----------------------------|-----------------------|-----------------|-----------|------------------|
| Pièce1.STL                | `base_plate.stl`      | 150×80×3        | 0.997 (solid slab) | Bottom mounting plate |
| Pièce2.STL                | `main_frame.stl`      | 153×80×204      | 0.056 (hollow tower) | Main chassis tower (largest, most frame-like part) |
| Pièce3.STL                | `shelf_panel_a.stl`   | 147×80×20       | 0.171 (ribbed) | Deck/shelf panel |
| "piece 3 la deuxiemme.STL"| `shelf_panel_b.stl`   | 147×80×20       | 0.171 (identical to Pièce3) | Matching duplicate deck/shelf panel |
| Pièce4.STL                | `bracket_arm.stl`     | 153×207×27      | 0.133 (curved, 1 pivot hole) | Rigid accessory bracket |
| piece 5.STL                | `side_panel.stl`      | 153×34×204      | 0.115 | Second wall of the tower (matches Pièce2's height/X-extent) |

**Important finding:** none of the 6 original parts is wheel-shaped. A
wheel has two equal dimensions (diameter × diameter) and one short
dimension (width); every original part here has three *different*
dimensions with high aspect ratios — they are all flat panels or a tall
hollow frame, consistent with a small enclosure/tower assembly, not a
two-wheeled drivetrain.

This was flagged explicitly rather than quietly mislabeling a panel as a
"wheel." Per your direction, two new wheel meshes were generated from
scratch (`wheel_left.stl`, `wheel_right.stl`) as true cylinders —
radius 40 mm, width 20 mm — sized to be proportionate to the 153×80×204 mm
chassis tower. Their geometry was verified against the analytic cylinder
volume formula (πr²h) and matched within 0.3% (discretization error from
the 48-segment mesh), and the centroid sits exactly at the mesh origin.

All renders and analysis scripts used to reach these conclusions are
available on request if you want to double check the classification.

## 2. Assembly / kinematic design

- `base_link` = `main_frame` (tower) + `side_panel` (second wall) +
  `shelf_panel_a`/`b` (top/bottom decks) + `base_plate` (underside) +
  `bracket_arm` (rigid accessory). All six are visual-only meshes fused
  rigidly into one link — only the wheels get actuated joints, per the
  hard constraint.
- `base_link`'s origin is placed **at wheel-axle height**, with the tower
  extending upward from there. Combined system center of mass sits
  **~46.5 mm above the axle**, with only a two-point (line) ground
  contact from the wheels — this is a real inverted pendulum: it has no
  passive pitch stability and will tip over without an active controller,
  not just a robot labeled as one.
- Collision geometry is **always primitives** (boxes for the chassis,
  cylinders for the wheels) — STL meshes are visual-only throughout, per
  the hard constraint.
- Every link has an explicitly computed mass/inertia tensor (closed-form
  solid-box and solid-cylinder formulas in `urdf/macros.xacro`), not
  placeholder values.

## 3. Package layout

```
robot_description/
├── package.xml, CMakeLists.txt
├── urdf/
│   ├── balancer_robot.xacro   (top-level, global properties)
│   ├── materials.xacro        (colors)
│   ├── macros.xacro           (box/cylinder inertia macros)
│   ├── base.xacro             (base_link: 6 fused chassis panels)
│   ├── wheels.xacro           (left/right wheel links + continuous joints)
│   ├── sensors.xacro          (IMU link + Gazebo IMU plugin)
│   └── gazebo.xacro           (gazebo_ros_init/factory, diff_drive, joint_state_publisher)
├── meshes/                    (8 STLs: 6 original chassis panels + 2 generated wheels)
├── launch/
│   ├── balancer_sim.launch.py (Gazebo + spawn_entity + robot_state_publisher + TF)
│   ├── balancer_world.world
│   └── balance_controller.py  (reference PD balance controller, optional)
└── rviz/balancer.rviz
```

## 4. Build & run (ROS 2 Humble + Gazebo Classic 11)

```bash
# from your colcon workspace
cp -r robot_description ~/ros2_ws/src/
cd ~/ros2_ws
colcon build --packages-select robot_description
source install/setup.bash

# launch Gazebo, spawn the robot, start robot_state_publisher + TF
ros2 launch robot_description balancer_sim.launch.py

# optional: also start a balance controller (pid is the default; lqr is also available)
ros2 launch robot_description balancer_sim.launch.py controller_type:=pid
ros2 launch robot_description balancer_sim.launch.py controller_type:=lqr
```

Manual spawn (if you want to call it yourself instead of via the launch
file):
```bash
ros2 run gazebo_ros spawn_entity.py -topic robot_description -entity balancer_robot
```

Drive it manually (controller off): the robot will fall over almost
immediately, since nothing is correcting the tilt — that's expected and
confirms the inverted-pendulum dynamics are real, not just stated.

```bash
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.2}}'
```

## 5. TF tree

`map → odom` is published as a **static identity transform** from the
launch file (for simulation convenience — there's no real localization
stack here). `odom → base_link` comes from the Gazebo `diff_drive`
plugin's odometry. `base_link → {left,right}_wheel_link` comes from
`robot_state_publisher`, fed live joint states from the Gazebo
`joint_state_publisher` plugin.

## 6. Known limitations / things you may want to revisit

- The reference balance controller (`balance_controller.py`) uses
  starting-point PD gains (kp=95, kd=50) — these are **not tuned** for the
  exact mass/inertia in `base.xacro`; you'll likely need to adjust them
  in simulation.
- The LQR controller (`lqr_controller.py`) gains were originally derived
  for a mass model that didn't match this chassis; they've since been
  recomputed from the actual `frame_mass`/`wheel_mass`/`frame_z` values in
  `balancer_robot.xacro` and `base.xacro` (see the comment in that file
  for the derivation and the resulting closed-loop eigenvalues). These
  are correctness-fixed, not hand-tuned — you may still want to adjust
  the LQR `Q`/`R` weighting in simulation for response feel.
- `bracket_arm.stl` (Pièce4) has a pivot hole in the original geometry
  but nothing in this task's scope tells it what it should pivot
  against, so it's mounted rigidly. If it was meant to be a moving
  part (e.g., a sensor tilt mechanism), let me know what it should
  articulate against and I'll add a joint for it.
- The two wheel meshes are placeholder-but-correct cylinders, not a
  scan/CAD model of a real wheel (no tread pattern, hub bolts, etc.). If
  you have or want a more detailed wheel design, swap the STL files —
  the URDF references them by filename only and doesn't otherwise care
  about surface detail.
=======
# self-balancing-robot-with-computer-vision
>>>>>>> 27a12f72c41a7ca0806f101f4c01bca5c1707fc5
