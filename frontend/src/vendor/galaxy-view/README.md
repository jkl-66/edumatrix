# Galaxy View integration

Upstream: https://github.com/Longwind1984/galaxy-view
Revision: b49b60cb04687783153f24ff7f9b0a0af59334af (0.6.1)
License: MIT; the original copyright and permission text is retained in LICENSE.

The render/, interactions/, layout/, timing/, quality/ and supporting data
modules are copied from the fixed upstream revision. The active integration
imports AggregateRenderer, CameraDirector and MainThreadForceLayout directly:
native Three.js Points shaders, bloom, nebula/starfield, curved links,
three-dimensional d3 physics, reveal animation, camera flights, orbit/pan/zoom
and keyboard flight. All eight upstream style presets are available.

EduMatrix adds the course/profile data adapter, chapter/mastery colors, contextual
labels with screen-space collision avoidance, one/two-hop relation focus,
filtering, source navigation and fullscreen controls. Deep Field is the default
fully spatial layout; paper mode uses the current product background. Node size
and background star density are adjusted for a course of 83 knowledge points.
This is an adaptation
of the open-source graph mechanism in the existing web product, not the Obsidian
plugin runtime. No Obsidian vault or API is required. The view reads existing
course relations and learning evidence; graph interaction does not update scores.

The earlier circle-label/3d-force-graph hybrid has been replaced. The full graph
may contain projected crossings when rotated. Local focus reveals
the selected node and its actual neighbors. Layout uses deterministic starting
positions and settles after a bounded simulation; no new semantic edges are added.
