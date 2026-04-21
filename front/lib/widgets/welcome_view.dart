// 첫 화면 (로고, 추천 질문)
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../theme.dart';
import '../models/chat_models.dart';

class WelcomeView extends StatelessWidget {
  final List<SuggestedQuestion> suggestions;
  final ValueChanged<String> onSuggestionTap;

  const WelcomeView({
    super.key,
    required this.suggestions,
    required this.onSuggestionTap,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(
        children: [
          const SizedBox(height: 60),

          // BeBot 로고 아이콘
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              color: AppColors.primarySurface,
              borderRadius: BorderRadius.circular(20),
            ),
            child: const Icon(
              Icons.smart_toy_rounded,
              size: 38,
              color: AppColors.primaryDark,
            ),
          )
              .animate()
              .fadeIn(duration: 500.ms)
              .scale(begin: const Offset(0.8, 0.8)),

          const SizedBox(height: 16),

          // 타이틀
          Text(
            'BeBot',
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                ),
          ).animate().fadeIn(delay: 200.ms, duration: 400.ms),

          const SizedBox(height: 28),

          // 환영 메시지
          Text(
            '반가워요, 비봇이에요!\n무엇을 도와드릴까요?',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  height: 1.45,
                ),
          ).animate().fadeIn(delay: 400.ms, duration: 500.ms),

          const SizedBox(height: 40),

          // 추천 질문들
          ...List.generate(suggestions.length, (i) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _SuggestionChip(
                text: suggestions[i].text,
                onTap: () => onSuggestionTap(suggestions[i].text),
              ),
            )
                .animate()
                .fadeIn(delay: (600 + i * 150).ms, duration: 400.ms)
                .slideY(begin: 0.15, end: 0);
          }),

          const SizedBox(height: 40),
        ],
      ),
    );
  }
}

class _SuggestionChip extends StatelessWidget {
  final String text;
  final VoidCallback onTap;

  const _SuggestionChip({required this.text, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          decoration: BoxDecoration(
            color: AppColors.userBubble.withOpacity(0.6),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: AppColors.primary.withOpacity(0.15),
              width: 1,
            ),
          ),
          child: Text(
            text,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w500,
                  height: 1.5,
                ),
          ),
        ),
      ),
    );
  }
}
