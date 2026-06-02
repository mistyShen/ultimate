ultimate_clinical_journal_tokens <- function() {
  list(
    style_id = "clinical_journal_v1",
    style_cn = "临床期刊版",
    background = "#FFFFFF",
    text = "#1F2937",
    axis = "#334155",
    grid = "#E5E7EB",
    muted = "#64748B",
    primary = "#2F5D8C",
    secondary = "#6F8FAF",
    case = "#B42318",
    control = "#1D4ED8",
    accent = "#0F766E",
    neutral = "#94A3B8"
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
