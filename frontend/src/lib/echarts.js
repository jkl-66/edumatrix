import * as echarts from 'echarts/core'
import { GraphChart, LineChart, PieChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  GraphicComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Register only the chart types used by EduMatrix instead of the full ECharts bundle.
echarts.use([
  GraphChart,
  LineChart,
  PieChart,
  RadarChart,
  GridComponent,
  GraphicComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

export { echarts }
