// 사용자/봇 말풍선
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import '../theme.dart';
import '../models/chat_models.dart';

class ChatBubble extends StatelessWidget {
  final ChatMessage message;
  final VoidCallback? onSourcesTap;

  const ChatBubble({
    super.key,
    required this.message,
    this.onSourcesTap,
  });

  @override
  Widget build(BuildContext context) {
    if (message.isUser) {
      return _UserBubble(message: message);
    }
    return _BotBubble(message: message, onSourcesTap: onSourcesTap);
  }
}

// ─── 사용자 말풍선 ─────────────────────────────────────
class _UserBubble extends StatelessWidget {
  final ChatMessage message;
  const _UserBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.55,
          ),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            decoration: const BoxDecoration(
              color: AppColors.userBubble,
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(20),
                topRight: Radius.circular(20),
                bottomLeft: Radius.circular(20),
                bottomRight: Radius.circular(6),
              ),
            ),
            child: Text(
              message.content,
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: AppColors.textPrimary,
                  ),
            ),
          ),
        ),
      ),
    );
  }
}

// ─── 봇 말풍선 ────────────────────────────────────────
class _BotBubble extends StatelessWidget {
  final ChatMessage message;
  final VoidCallback? onSourcesTap;

  const _BotBubble({required this.message, this.onSourcesTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 16, right: 40, top: 8, bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 봇 아바타
          Container(
            width: 32,
            height: 32,
            margin: const EdgeInsets.only(top: 4),
            decoration: BoxDecoration(
              color: AppColors.primarySurface,
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(
              Icons.smart_toy_rounded,
              size: 18,
              color: AppColors.primaryDark,
            ),
          ),
          const SizedBox(width: 10),

          // 메시지 본문
          Flexible(
           child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 로딩 상태
                if (message.isLoading) _buildLoadingIndicator(context),

                // 답변 텍스트
                if (!message.isLoading && message.content.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 14),
                    decoration: const BoxDecoration(
                      color: AppColors.botBubble,
                      borderRadius: BorderRadius.only(
                        topLeft: Radius.circular(6),
                        topRight: Radius.circular(20),
                        bottomLeft: Radius.circular(20),
                        bottomRight: Radius.circular(20),
                      ),
                    ),
                    child: MarkdownBody(
                      data: message.content,
                      styleSheet: MarkdownStyleSheet(
                        p: Theme.of(context)
                            .textTheme
                            .bodyLarge
                            ?.copyWith(height: 1.7),
                        h2: Theme.of(context)
                            .textTheme
                            .headlineMedium
                            ?.copyWith(fontSize: 17),
                        h3: Theme.of(context)
                            .textTheme
                            .headlineMedium
                            ?.copyWith(fontSize: 15),
                        listBullet: Theme.of(context).textTheme.bodyLarge,
                        blockSpacing: 12,
                      ),
                      selectable: true,
                    ),
                  ),

                // 출처 버튼
                if (!message.isLoading &&
                    message.sources != null &&
                    !message.sources!.isEmpty)
                  _SourceBadge(
                    sources: message.sources!,
                    onTap: onSourcesTap,
                  ),
              ],
            ),
           ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingIndicator(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      decoration: BoxDecoration(
        color: AppColors.botBubble,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const _TypingDot(delay: 0),
          const SizedBox(width: 6),
          const _TypingDot(delay: 200),
          const SizedBox(width: 6),
          const _TypingDot(delay: 400),
          const SizedBox(width: 12),
          Text(
            '답변을 생성하고 있어요...',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textTertiary,
                ),
          ),
        ],
      ),
    );
  }
}

// ─── 출처 배지 ────────────────────────────────────────
class _SourceBadge extends StatelessWidget {
  final SourceInfo sources;
  final VoidCallback? onTap;

  const _SourceBadge({required this.sources, this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.divider),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.format_quote_rounded,
                    size: 16, color: AppColors.primary),
                const SizedBox(width: 6),
                Text(
                  '출처 ${sources.totalCount}건',
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: AppColors.primary,
                        fontWeight: FontWeight.w600,
                      ),
                ),
                const SizedBox(width: 4),
                if (sources.webSources.isNotEmpty)
                  const _MiniTag(label: '웹', color: AppColors.webBadge),
                if (sources.bookSources.isNotEmpty)
                  const _MiniTag(label: '책', color: AppColors.bookBadge),
                if (sources.videoSources.isNotEmpty)
                  const _MiniTag(label: '영상', color: AppColors.videoBadge),
                const SizedBox(width: 4),
                const Icon(Icons.chevron_right_rounded,
                    size: 18, color: AppColors.textTertiary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MiniTag extends StatelessWidget {
  final String label;
  final Color color;
  const _MiniTag({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(left: 4),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

// ─── 타이핑 점 애니메이션 ──────────────────────────────
class _TypingDot extends StatefulWidget {
  final int delay;
  const _TypingDot({required this.delay});

  @override
  State<_TypingDot> createState() => _TypingDotState();
}

class _TypingDotState extends State<_TypingDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _animation = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
    Future.delayed(Duration(milliseconds: widget.delay), () {
      if (mounted) _controller.repeat(reverse: true);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (_, __) => Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          color: AppColors.primary.withOpacity(0.3 + _animation.value * 0.5),
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}
