const { test, expect } = require('@playwright/test');

/**
 * EduMatrix 智教矩阵 — 前端极简瑞士风视觉回归测试 (Visual Regression Test Spec)
 * 
 * 核心目的：
 * 本测试由 `oma-qa` 和 `code-reviewer` 智能体调用，用于对 Vue 3 前端界面进行像素级的比对，
 * 彻底杜绝 AI 大模型在微调组件样式时引入“廉价、粗糙的渐变圆角味”，死守瑞士极简风（Swiss Grid Style）的视觉档次。
 * 
 * 🛠️ 本地运行指南：
 * 1. 在 `frontend` 目录下安装 Playwright：
 *    cd frontend
 *    npm install -D @playwright/test
 *    npx playwright install
 * 
 * 2. 启动本地前端开发服务：
 *    npm run dev
 * 
 * 3. 运行视觉比对测试：
 *    npx playwright test tests/visual_regression.spec.js --update-snapshots  (首次生成基准快照)
 *    npx playwright test tests/visual_regression.spec.js                     (后续运行像素级像素比对)
 */

test.describe('EduMatrix Swiss Minimalist UI - Visual Regression Testing', () => {

  test.beforeEach(async ({ page }) => {
    // 访问本地 Vite 前端服务（绕过梯子，强制绑定 127.0.0.1）
    await page.goto('http://127.0.0.1:5173/');
    // 等待核心 DOM 树渲染加载完毕
    await page.waitForLoadState('networkidle');
  });

  test('Dashboard Page - Baseline Snapshot Comparison', async ({ page }) => {
    // 1. 验证仪表盘（Dashboard）主页卡片布局的瑞士极简风网格对齐
    const dashboardContainer = page.locator('#app');
    
    // 2. 截取当前 DOM 视口快照，与已存的基准快照进行像素比对
    // 如果像素差异大于预设阈值（例如 1.5%），测试将强行拦截并打回重构
    await expect(dashboardContainer).toHaveScreenshot('dashboard-page-baseline.png', {
      maxDiffPixels: 100, // 允许最大 100 像素偏差以容忍极小的跨平台渲染差异
      threshold: 0.2,     // 像素颜色判定阈值
    });
  });

  test('Multi-Agent Chat Interface - Glassmorphism Bubbles Verification', async ({ page }) => {
    // 1. 跳转到 Chat 智能体交互枢纽
    await page.click('text=Chat');
    await page.waitForTimeout(1000); // 等待过渡微动画执行完毕

    // 2. 定位多智能体后台思考气泡与 SSE 流式渲染面板
    const chatPanel = page.locator('.chat-container');
    
    // 3. 验证毛玻璃（Glassmorphism）与 Outfit 现代字体的视觉纯净度
    if (await chatPanel.isVisible()) {
      await expect(chatPanel).toHaveScreenshot('chat-interface-glassmorphism.png', {
        threshold: 0.2,
      });
    }
  });

  test('Adaptive Quiz Card - Multi-step Scoring UI Alignment', async ({ page }) => {
    // 1. 跳转到自适应 Quiz 评测页面
    await page.click('text=Quiz');
    await page.waitForTimeout(1000);

    const quizCard = page.locator('.quiz-card');

    // 2. 验证多步精细化打分（Concept-level grading）的网格对齐与排版自洽性
    if (await quizCard.isVisible()) {
      await expect(quizCard).toHaveScreenshot('quiz-adaptive-card.png', {
        threshold: 0.2,
      });
    }
  });
});
