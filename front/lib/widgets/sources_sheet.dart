// 출처 상세 바텀 시트 (영상 재생 포함)
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:youtube_player_flutter/youtube_player_flutter.dart';
import '../theme.dart';
import '../models/chat_models.dart';

/// 출처 상세 보기 바텀시트
class SourcesSheet extends StatelessWidget {
  final SourceInfo sources;

  const SourcesSheet({super.key, required this.sources});

  static void show(BuildContext context, SourceInfo sources) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => SourcesSheet(sources: sources),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.65,
      minChildSize: 0.3,
      maxChildSize: 0.92,
      builder: (_, scrollController) {
        return Container(
          decoration: const BoxDecoration(
            color: AppColors.background,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: Column(
            children: [
              // 핸들 바
              Container(
                margin: const EdgeInsets.only(top: 12, bottom: 8),
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),

              // 헤더
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                child: Row(
                  children: [
                    const Icon(Icons.format_quote_rounded,
                        color: AppColors.primary, size: 22),
                    const SizedBox(width: 8),
                    Text(
                      '출처 정보',
                      style:
                          Theme.of(context).textTheme.headlineMedium?.copyWith(
                                fontSize: 18,
                              ),
                    ),
                    const Spacer(),
                    Text(
                      '총 ${sources.totalCount}건',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ],
                ),
              ),
              const Divider(height: 1, color: AppColors.divider),

              // 출처 목록
              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.all(16),
                  children: [
                    // 영상 출처
                    if (sources.videoSources.isNotEmpty) ...[
                      const _SectionHeader(
                          icon: Icons.video_camera_back,
                          label: '영상 자료',
                          color: AppColors.videoBadge),
                      ...sources.videoSources
                          .map((v) => _VideoSourceCard(source: v)),
                      const SizedBox(height: 20),
                    ],

                    // 웹 출처
                    if (sources.webSources.isNotEmpty) ...[
                      const _SectionHeader(
                          icon: Icons.language_rounded,
                          label: '웹사이트 자료',
                          color: AppColors.webBadge),
                      ...sources.webSources
                          .map((w) => _WebSourceCard(source: w)),
                      const SizedBox(height: 20),
                    ],

                    // 책 출처
                    if (sources.bookSources.isNotEmpty) ...[
                      const _SectionHeader(
                          icon: Icons.menu_book_rounded,
                          label: '책 자료',
                          color: AppColors.bookBadge),
                      ...sources.bookSources
                          .map((b) => _BookSourceCard(source: b)),
                    ],

                    const SizedBox(height: 40),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

// ─── 섹션 헤더 ────────────────────────────────────────
class _SectionHeader extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _SectionHeader({
    required this.icon,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: color,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}

// ─── 영상 출처 카드 (인앱 재생 지원) ─────────────────────
class _VideoSourceCard extends StatefulWidget {
  final VideoSource source;
  const _VideoSourceCard({required this.source});

  @override
  State<_VideoSourceCard> createState() => _VideoSourceCardState();
}

class _VideoSourceCardState extends State<_VideoSourceCard> {
  YoutubePlayerController? _playerController;
  bool _isPlayerVisible = false;
  // 에러 101/150: 임베드 비허용, 100: 영상 없음, 5: HTML5 오류
  bool _embedBlocked = false;

  void _initPlayer() {
    final ytId = widget.source.youtubeId ?? '';
    if (ytId.isEmpty) return;

    _playerController = YoutubePlayerController(
      initialVideoId: ytId,
      flags: YoutubePlayerFlags(
        autoPlay: true,
        startAt: widget.source.startTime.toInt(),
        mute: false,
      ),
    );
    _playerController!.addListener(_onPlayerStateChange);
    setState(() => _isPlayerVisible = true);
  }

  void _onPlayerStateChange() {
    if (!mounted) return;
    final value = _playerController?.value;
    if (value == null) return;
    // hasError 감지: 임베드 차단(101, 150), 영상 없음(100), HTML5 오류(5)
    if (value.hasError && !_embedBlocked) {
      setState(() => _embedBlocked = true);
    }
  }

  Future<void> _openInYoutube() async {
    final url = widget.source.url.isNotEmpty
        ? widget.source.url
        : 'https://www.youtube.com/watch?v=${widget.source.videoId}&t=${widget.source.startTime.toInt()}';
    final uri = Uri.tryParse(url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  void dispose() {
    _playerController?.removeListener(_onPlayerStateChange);
    _playerController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 영상 정보 + 재생 버튼
          InkWell(
            onTap: _isPlayerVisible ? null : _initPlayer,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  // 썸네일 또는 재생 아이콘
                  Container(
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      color: AppColors.videoBadge.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      _isPlayerVisible
                          ? Icons.pause_circle_filled
                          : Icons.play_circle_filled_rounded,
                      color: AppColors.videoBadge,
                      size: 30,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.source.title,
                          style: Theme.of(context)
                              .textTheme
                              .labelLarge
                              ?.copyWith(fontWeight: FontWeight.w600),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${_formatTime(widget.source.startTime)} ~ ${_formatTime(widget.source.endTime)}',
                          style: Theme.of(context)
                              .textTheme
                              .labelSmall
                              ?.copyWith(color: AppColors.videoBadge),
                        ),
                      ],
                    ),
                  ),
                  if (!_isPlayerVisible)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: AppColors.videoBadge.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Text(
                        '재생',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.videoBadge,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),

          // 임베드 차단 시 외부 열기 폴백
          if (_embedBlocked)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '이 영상은 앱 내 재생이 제한되어 있습니다.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textTertiary,
                        ),
                  ),
                  const SizedBox(height: 8),
                  GestureDetector(
                    onTap: _openInYoutube,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: AppColors.videoBadge.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.open_in_new_rounded,
                              size: 14, color: AppColors.videoBadge),
                          SizedBox(width: 6),
                          Text(
                            'YouTube에서 열기',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: AppColors.videoBadge,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),

          // 인앱 YouTube 플레이어
          // YoutubePlayerBuilder로 감싸야 ListView 내 PlatformView가 정상 렌더링됨
          if (_isPlayerVisible && !_embedBlocked && _playerController != null)
            YoutubePlayerBuilder(
              player: YoutubePlayer(
                controller: _playerController!,
                showVideoProgressIndicator: true,
                progressIndicatorColor: AppColors.videoBadge,
                progressColors: const ProgressBarColors(
                  playedColor: AppColors.videoBadge,
                  handleColor: AppColors.videoBadge,
                ),
              ),
              builder: (context, player) => ClipRRect(
                borderRadius:
                    const BorderRadius.vertical(bottom: Radius.circular(16)),
                child: player,
              ),
            ),

          // 스니펫
          if (widget.source.snippet.isNotEmpty && !_isPlayerVisible)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: Text(
                widget.source.snippet,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppColors.textTertiary,
                      height: 1.5,
                    ),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ),
        ],
      ),
    );
  }

  String _formatTime(double seconds) {
    final min = (seconds / 60).floor();
    final sec = (seconds % 60).floor();
    return '${min.toString().padLeft(2, '0')}:${sec.toString().padLeft(2, '0')}';
  }
}

// ─── 웹 출처 카드 ─────────────────────────────────────
class _WebSourceCard extends StatelessWidget {
  final WebSource source;
  const _WebSourceCard({required this.source});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          onTap: () => _openUrl(source.url),
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.divider),
            ),
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: AppColors.webBadge.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(Icons.language_rounded,
                      color: AppColors.webBadge, size: 20),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        source.title,
                        style: Theme.of(context)
                            .textTheme
                            .labelLarge
                            ?.copyWith(fontWeight: FontWeight.w600),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (source.url.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(
                          _shortenUrl(source.url),
                          style:
                              Theme.of(context).textTheme.labelSmall?.copyWith(
                                    color: AppColors.webBadge,
                                  ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ],
                  ),
                ),
                const Icon(Icons.open_in_new_rounded,
                    size: 16, color: AppColors.textTertiary),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _shortenUrl(String url) {
    try {
      final uri = Uri.parse(url);
      return uri.host +
          (uri.path.length > 30 ? '${uri.path.substring(0, 30)}...' : uri.path);
    } catch (_) {
      return url.length > 40 ? '${url.substring(0, 40)}...' : url;
    }
  }

  Future<void> _openUrl(String url) async {
    final uri = Uri.tryParse(url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

// ─── 책 출처 카드 ─────────────────────────────────────
class _BookSourceCard extends StatelessWidget {
  final BookSource source;
  const _BookSourceCard({required this.source});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.divider),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.bookBadge.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.menu_book_rounded,
                color: AppColors.bookBadge, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  source.bookName,
                  style: Theme.of(context)
                      .textTheme
                      .labelLarge
                      ?.copyWith(fontWeight: FontWeight.w600),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 3),
                Text(
                  'p.${source.page}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: AppColors.bookBadge,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
