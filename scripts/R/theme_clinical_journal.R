ultimate_clinical_journal_tokens <- function() {
  list(
    style_id = "clinical_journal_v3_soft_color",
    style_cn = "临床期刊版-柔彩科研配色",
    background = "#FFFFFF",
    text = "#3B4354",
    axis = "#667085",
    grid = "#ECEFF4",
    muted = "#8A94A6",
    primary = "#6C7BEF",
    secondary = "#5EC4B6",
    case = "#E36A6A",
    control = "#4A90D9",
    accent = "#D8A24A",
    neutral = "#BAC3D0",
    bar = "#5FAFC1",
    bar_light = "#D8E7EC",
    bar_highlight = "#E36A6A",
    heatmap_low = "#5DA9C7",
    heatmap_mid = "#F8FAFC",
    heatmap_high = "#D96C75"
  )
}

ultimate_theme_clinical_journal <- function(base_size = 10, base_family = "sans") {
  tokens <- ultimate_clinical_journal_tokens()
  ggplot2::theme_minimal(base_size = base_size, base_family = base_family) +
    ggplot2::theme(
      plot.background = ggplot2::element_rect(fill = tokens$background, color = NA),
      panel.background = ggplot2::element_rect(fill = tokens$background, color = NA),
      panel.grid.major = ggplot2::element_line(color = tokens$grid, linewidth = 0.3),
      panel.grid.minor = ggplot2::element_blank(),
      axis.text = ggplot2::element_text(color = tokens$axis),
      axis.title = ggplot2::element_text(color = tokens$text),
      plot.title = ggplot2::element_text(color = tokens$text, face = "bold"),
      legend.background = ggplot2::element_blank(),
      legend.key = ggplot2::element_blank()
    )
}

ultimate_scale_condition <- function() {
  tokens <- ultimate_clinical_journal_tokens()
  ggplot2::scale_color_manual(
    values = c(
      control = tokens$control,
      Control = tokens$control,
      treated = tokens$case,
      Tumor = tokens$case,
      case = tokens$case
    )
  )
}

ultimate_scale_fill_condition <- function() {
  tokens <- ultimate_clinical_journal_tokens()
  ggplot2::scale_fill_manual(
    values = c(
      control = tokens$control,
      Control = tokens$control,
      treated = tokens$case,
      Tumor = tokens$case,
      case = tokens$case
    )
  )
}

ultimate_save_plot <- function(filename, plot, width = 6, height = 4, dpi = 180) {
  ggplot2::ggsave(filename, plot = plot, width = width, height = height, dpi = dpi, bg = "white")
}

ultimate_scale_heatmap <- function(limits = c(-2, 2), midpoint = 0) {
  tokens <- ultimate_clinical_journal_tokens()
  ggplot2::scale_fill_gradient2(
    low = tokens$heatmap_low,
    mid = tokens$heatmap_mid,
    high = tokens$heatmap_high,
    midpoint = midpoint,
    limits = limits,
    oob = scales::squish
  )
}
