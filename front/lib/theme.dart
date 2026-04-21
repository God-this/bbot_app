import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  // Primary palette - warm sage green (from Figma reference)
  static const Color primary = Color(0xFF8BA888);
  static const Color primaryLight = Color(0xFFB5CDB2);
  static const Color primarySurface = Color(0xFFE8F0E6);
  static const Color primaryDark = Color(0xFF5E7E5B);

  // Neutrals
  static const Color background = Color(0xFFF8F7F4);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceVariant = Color(0xFFF2F1ED);
  static const Color textPrimary = Color(0xFF2C2C2C);
  static const Color textSecondary = Color(0xFF6B6B6B);
  static const Color textTertiary = Color(0xFF9B9B9B);
  static const Color divider = Color(0xFFE5E3DE);

  // Chat bubbles
  static const Color userBubble = Color(0xFFD4E4D1);
  static const Color botBubble = Color(0xFFF5F4F0);

  // Accent
  static const Color accent = Color(0xFFD4A574);
  static const Color error = Color(0xFFD35B5B);
  static const Color info = Color(0xFF5B8FD3);

  // Source badges
  static const Color webBadge = Color(0xFF5B8FD3);
  static const Color bookBadge = Color(0xFFD4A574);
  static const Color videoBadge = Color(0xFFD35B7A);
}

class AppTheme {
  static ThemeData get theme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: const ColorScheme.light(
        primary: AppColors.primary,
        onPrimary: Colors.white,
        secondary: AppColors.accent,
        surface: AppColors.surface,
        onSurface: AppColors.textPrimary,
        error: AppColors.error,
      ),
      textTheme: GoogleFonts.notoSansKrTextTheme().copyWith(
        headlineLarge: GoogleFonts.notoSansKr(
          fontSize: 26,
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
          height: 1.4,
        ),
        headlineMedium: GoogleFonts.notoSansKr(
          fontSize: 20,
          fontWeight: FontWeight.w600,
          color: AppColors.textPrimary,
        ),
        bodyLarge: GoogleFonts.notoSansKr(
          fontSize: 16,
          fontWeight: FontWeight.w400,
          color: AppColors.textPrimary,
          height: 1.6,
        ),
        bodyMedium: GoogleFonts.notoSansKr(
          fontSize: 14,
          fontWeight: FontWeight.w400,
          color: AppColors.textSecondary,
          height: 1.5,
        ),
        labelLarge: GoogleFonts.notoSansKr(
          fontSize: 14,
          fontWeight: FontWeight.w500,
          color: AppColors.textPrimary,
        ),
        labelSmall: GoogleFonts.notoSansKr(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: AppColors.textTertiary,
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.background,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        centerTitle: true,
        titleTextStyle: GoogleFonts.notoSansKr(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: AppColors.textPrimary,
        ),
        iconTheme: const IconThemeData(color: AppColors.textPrimary),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surfaceVariant,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(24),
          borderSide: BorderSide.none,
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        hintStyle: GoogleFonts.notoSansKr(
          fontSize: 15,
          color: AppColors.textTertiary,
        ),
      ),
    );
  }
}
