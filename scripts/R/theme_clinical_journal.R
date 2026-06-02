ultimate_style_registry <- function() {
  list(
    soft_color = list(style_id = "clinical_journal_v5_aurora_color", style_cn = "临床期刊版-极光柔彩", text = "#4B5368", axis = "#7B8498", grid = "#EEF2F7", primary = "#8C6FF7", secondary = "#31C5B7", case = "#F26F8F", control = "#4EA4F5", accent = "#F2B84B", neutral = "#C9D1DE", bar = "#31B7C5", bar_light = "#DDF4F3", bar_highlight = "#F26F8F", heatmap_low = "#43A5F5", heatmap_mid = "#FBFCFF", heatmap_high = "#F06A8F"),
    okabe_ito = list(style_id = "scientific_okabe_ito", style_cn = "Okabe-Ito 色盲友好", text = "#3E4654", axis = "#667085", grid = "#ECEFF3", primary = "#009E73", secondary = "#56B4E9", case = "#D55E00", control = "#0072B2", accent = "#E69F00", neutral = "#B7C0CC", bar = "#56B4E9", bar_light = "#D9EEF7", bar_highlight = "#D55E00", heatmap_low = "#0072B2", heatmap_mid = "#FAFAFA", heatmap_high = "#D55E00"),
    colorbrewer_set2 = list(style_id = "colorbrewer_set2_soft", style_cn = "ColorBrewer Set2 柔和分类", text = "#3F4652", axis = "#667085", grid = "#EEF1F4", primary = "#66C2A5", secondary = "#8DA0CB", case = "#FC8D62", control = "#8DA0CB", accent = "#E78AC3", neutral = "#B3B3B3", bar = "#66C2A5", bar_light = "#DDEFEA", bar_highlight = "#FC8D62", heatmap_low = "#8DA0CB", heatmap_mid = "#FBFBFB", heatmap_high = "#FC8D62"),
    nature_modern = list(style_id = "journal_nature_modern", style_cn = "Nature 风格现代科研", text = "#3D4552", axis = "#697386", grid = "#ECEFF3", primary = "#3C5488", secondary = "#00A087", case = "#E64B35", control = "#4DBBD5", accent = "#F39B7F", neutral = "#B9C1CD", bar = "#4DBBD5", bar_light = "#D8EEF4", bar_highlight = "#E64B35", heatmap_low = "#4DBBD5", heatmap_mid = "#F8FAFC", heatmap_high = "#E64B35"),
    lancet_clinical = list(style_id = "journal_lancet_clinical", style_cn = "Lancet 风格临床强化", text = "#3F4652", axis = "#667085", grid = "#ECEFF3", primary = "#00468B", secondary = "#0099B4", case = "#AD002A", control = "#00468B", accent = "#42B540", neutral = "#ADB6B6", bar = "#0099B4", bar_light = "#D8EEF2", bar_highlight = "#AD002A", heatmap_low = "#00468B", heatmap_mid = "#FAFAFA", heatmap_high = "#AD002A"),
    jama_clean = list(style_id = "journal_jama_clean", style_cn = "JAMA 风格清爽克制", text = "#444B55", axis = "#6B7280", grid = "#EEF0F3", primary = "#374E55", secondary = "#00A1D5", case = "#B24745", control = "#00A1D5", accent = "#DF8F44", neutral = "#C4C7CE", bar = "#79AF97", bar_light = "#E2EFE9", bar_highlight = "#B24745", heatmap_low = "#00A1D5", heatmap_mid = "#FBFBFB", heatmap_high = "#B24745"),
    nejm_warm = list(style_id = "journal_nejm_warm", style_cn = "NEJM 风格暖色临床", text = "#444B55", axis = "#6B7280", grid = "#EFEDE9", primary = "#0072B5", secondary = "#20854E", case = "#BC3C29", control = "#0072B5", accent = "#E18727", neutral = "#C8C1B8", bar = "#6F99AD", bar_light = "#DDE9EE", bar_highlight = "#BC3C29", heatmap_low = "#0072B5", heatmap_mid = "#FAFAF7", heatmap_high = "#BC3C29")
  )
}

ultimate_clinical_journal_tokens <- function(style = "soft_color") {
  registry <- ultimate_style_registry()
  if (!style %in% names(registry)) {
    stop(sprintf("Unsupported style '%s'. Available: %s", style, paste(names(registry), collapse = ", ")))
  }
  c(list(background = "#FFFFFF", muted = "#8A94A6"), registry[[style]])
}

ultimate_theme_clinical_journal <- function(base_size = 10, base_family = "sans", style = "soft_color") {
  tokens <- ultimate_clinical_journal_tokens(style)
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

ultimate_scale_condition <- function(style = "soft_color") {
  tokens <- ultimate_clinical_journal_tokens(style)
  ggplot2::scale_color_manual(values = c(control = tokens$control, Control = tokens$control, treated = tokens$case, Tumor = tokens$case, case = tokens$case))
}

ultimate_scale_fill_condition <- function(style = "soft_color") {
  tokens <- ultimate_clinical_journal_tokens(style)
  ggplot2::scale_fill_manual(values = c(control = tokens$control, Control = tokens$control, treated = tokens$case, Tumor = tokens$case, case = tokens$case))
}

ultimate_save_plot <- function(filename, plot, width = 6, height = 4, dpi = 180) {
  ggplot2::ggsave(filename, plot = plot, width = width, height = height, dpi = dpi, bg = "white")
}

ultimate_scale_heatmap <- function(limits = c(-2, 2), midpoint = 0, style = "soft_color") {
  tokens <- ultimate_clinical_journal_tokens(style)
  ggplot2::scale_fill_gradient2(low = tokens$heatmap_low, mid = tokens$heatmap_mid, high = tokens$heatmap_high, midpoint = midpoint, limits = limits, oob = scales::squish)
}
