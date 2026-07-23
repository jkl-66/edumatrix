import asyncio

from code_exec_api import SandboxProcessRunner


THREE_D_CODE = """
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D

x = np.linspace(-5, 5, 50)
y = np.linspace(-5, 5, 50)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2))

fig = plt.figure(figsize=(8, 5))
ax = fig.add_subplot(111, projection='3d')
surf = ax.plot_surface(X, Y, Z, cmap='viridis', edgecolor='none', alpha=0.9)
fig.colorbar(surf, ax=ax, shrink=0.5, aspect=5)
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')
ax.set_title('3D surface')
plt.tight_layout()
plt.show()
"""


def test_three_dimensional_visual_output_is_not_text_truncated():
    runner = SandboxProcessRunner()
    try:
        stdout, stderr, _ = asyncio.run(runner._run_in_subprocess(THREE_D_CODE))
    finally:
        runner.executor.shutdown(wait=True)

    assert "data:image/png;base64," in stdout
    assert "输出已截断" not in stderr
    assert "可视化输出已截断" not in stderr


def test_visual_output_has_a_separate_transport_channel():
    runner = SandboxProcessRunner()
    source = runner._get_wrapper_script()
    runner.executor.shutdown(wait=True)
    assert "MAX_VISUAL_BYTES" in source
    assert "visual_buffer = LimitedBuffer(MAX_VISUAL_BYTES)" in source
    assert "===VISUAL_SEPARATOR===" in source
