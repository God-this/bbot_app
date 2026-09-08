// 메인 채팅 화면
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/chat_models.dart';
import '../theme.dart';
import '../services/chat_provider.dart';
import '../services/auth_provider.dart';
import '../widgets/welcome_view.dart';
import '../widgets/chat_bubble.dart';
import '../widgets/chat_input_bar.dart';
import '../widgets/sources_sheet.dart';
import '../widgets/history_drawer.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  static const _drawerMinWidth  = 240.0;
  static const _drawerMaxWidth  = 420.0;
  static const _drawerWidthPrefKey = 'history_drawer_width';

  final _scrollController = ScrollController();
  SourceInfo? _selectedSources;

  /// 사용자가 드래그로 지정한 드로어 폭 (null이면 화면 크기 기반 기본값)
  double? _userDrawerWidth;

  @override
  void initState() {
    super.initState();
    _restoreDrawerWidth();
  }

  Future<void> _restoreDrawerWidth() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getDouble(_drawerWidthPrefKey);
    if (saved != null && mounted) {
      setState(() => _userDrawerWidth = saved);
    }
  }

  Future<void> _persistDrawerWidth(double width) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(_drawerWidthPrefKey, width);
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _handleSourcesTap(BuildContext context, SourceInfo sources) {
    if (MediaQuery.of(context).size.width >= 700) {
      setState(() => _selectedSources = sources);
    } else {
      SourcesSheet.show(context, sources);
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  /// 화면 크기에 맞춘 드로어 기본 폭
  /// - 모바일: 화면 비율 기반이되 최대 320px
  /// - 태블릿/데스크톱: 고정 폭
  double _defaultDrawerWidth(BuildContext context) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    if (screenWidth < 600) {
      return (screenWidth * 0.85).clamp(0.0, 320.0);
    }
    return 300;
  }

  /// 현재 적용할 드로어 폭
  /// 사용자가 드래그로 조정한 값이 있으면 그 값을, 없으면 기본값을 쓴다.
  /// 어느 쪽이든 화면을 넘지 않도록 허용 범위 안으로 제한한다.
  double _drawerWidth(BuildContext context) {
    final width = _userDrawerWidth ?? _defaultDrawerWidth(context);
    return width.clamp(_drawerMinWidth, _maxDrawerWidth(context));
  }

  /// 좁은 화면에서 드로어가 본문을 완전히 덮지 않도록 상한을 낮춘다.
  double _maxDrawerWidth(BuildContext context) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    final limit = screenWidth * 0.85;
    return limit < _drawerMinWidth
        ? _drawerMinWidth
        : (limit < _drawerMaxWidth ? limit : _drawerMaxWidth);
  }

  void _handleDrawerResize(BuildContext context, double deltaX) {
    final next = (_drawerWidth(context) + deltaX)
        .clamp(_drawerMinWidth, _maxDrawerWidth(context));
    if (next != _userDrawerWidth) {
      setState(() => _userDrawerWidth = next);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(context),
      drawer: Drawer(
        width: _drawerWidth(context),
        child: _ResizableDrawerContent(
          onResize: (deltaX) => _handleDrawerResize(context, deltaX),
          onResizeEnd: () => _persistDrawerWidth(_drawerWidth(context)),
          child: HistoryDrawer(
            onSessionLoaded: () => setState(() => _selectedSources = null),
          ),
        ),
      ),
      onDrawerChanged: (isOpened) {
        if (isOpened) context.read<ChatProvider>().fetchSessions();
      },
      body: Consumer<ChatProvider>(
        builder: (context, chat, _) {
          return SafeArea(
            bottom: false,
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    children: [
                      // 채팅 영역
                      Expanded(
                        child: Builder(builder: (context) {
                          if (!chat.hasMessages) {
                            return WelcomeView(
                              suggestions: chat.suggestedQuestions,
                              onSuggestionTap: (text) {
                                chat.sendMessage(text.replaceAll('\n', ' '));
                                _scrollToBottom();
                              },
                            );
                          }

                          _scrollToBottom();

                          return Scrollbar(
                            controller: _scrollController,
                            child: ScrollConfiguration(
                              behavior: ScrollConfiguration.of(context)
                                  .copyWith(scrollbars: false),
                              child: ListView.builder(
                                controller: _scrollController,
                                padding: const EdgeInsets.symmetric(
                                    vertical: 16),
                                itemCount: chat.messages.length,
                                itemBuilder: (context, index) {
                                  final msg = chat.messages[index];

                                  Widget? dateDivider;
                                  if (index == 0 ||
                                      !_isSameDay(
                                        chat.messages[index - 1].timestamp,
                                        msg.timestamp,
                                      )) {
                                    dateDivider =
                                        _DateDivider(date: msg.timestamp);
                                  }

                                  return Center(
                                    child: ConstrainedBox(
                                      constraints:
                                          const BoxConstraints(maxWidth: 680),
                                      child: Column(
                                        children: [
                                          if (dateDivider != null) dateDivider,
                                          ChatBubble(
                                            message: msg,
                                            onSourcesTap: msg.sources != null
                                                ? () => _handleSourcesTap(
                                                    context, msg.sources!)
                                                : null,
                                          ),
                                        ],
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
                          );
                        }),
                      ),

                      // 입력 바
                      ChatInputBar(
                        isLoading: chat.isTyping,
                        onSend: (text) {
                          chat.sendMessage(text);
                          _scrollToBottom();
                        },
                      ),
                    ],
                  ),
                ),

                // 사이드 패널 (너비 700px 이상 + 출처 선택 시, 채팅과 50:50)
                if (_selectedSources != null &&
                    chat.hasMessages &&
                    MediaQuery.of(context).size.width >= 700)
                  Expanded(
                    child: SourcesSidePanel(
                      sources: _selectedSources!,
                      onClose: () => setState(() => _selectedSources = null),
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  static const String _adminPassword = 'bbot1234!';

  void _showAdminLogin(BuildContext context) {
    final controller = TextEditingController();
    bool obscure = true;

    showDialog(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('관리자 인증'),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          content: TextField(
            controller: controller,
            obscureText: obscure,
            autofocus: true,
            decoration: InputDecoration(
              hintText: '비밀번호를 입력하세요',
              suffixIcon: IconButton(
                icon: Icon(obscure ? Icons.visibility_off : Icons.visibility),
                onPressed: () => setDialogState(() => obscure = !obscure),
              ),
            ),
            onSubmitted: (_) => _tryAdminLogin(dialogContext, controller.text),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            TextButton(
              onPressed: () => _tryAdminLogin(dialogContext, controller.text),
              child: const Text(
                '확인',
                style: TextStyle(color: AppColors.primary),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _tryAdminLogin(BuildContext dialogContext, String input) {
    if (input == _adminPassword) {
      Navigator.pop(dialogContext);
      Navigator.pushNamed(dialogContext, '/admin');
    } else {
      ScaffoldMessenger.of(dialogContext).showSnackBar(
        const SnackBar(
          content: Text('비밀번호가 올바르지 않습니다.'),
          backgroundColor: Colors.redAccent,
        ),
      );
    }
  }

  void _showLogoutDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('로그아웃'),
        content: const Text('로그아웃 하시겠습니까?'),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              context.read<AuthProvider>().signOut();
            },
            child: const Text(
              '로그아웃',
              style: TextStyle(color: AppColors.error),
            ),
          ),
        ],
      ),
    );
  }

  PreferredSizeWidget _buildAppBar(BuildContext context) {
    return AppBar(
      title: GestureDetector(
        onLongPress: () => _showAdminLogin(context),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: AppColors.primarySurface,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(
                Icons.smart_toy_rounded,
                size: 16,
                color: AppColors.primaryDark,
              ),
            ),
            const SizedBox(width: 8),
            const Text('BeBot'),
          ],
        ),
      ),
      actions: [
        Consumer<ChatProvider>(
          builder: (context, chat, _) {
            if (!chat.hasMessages) return const SizedBox.shrink();
            return IconButton(
              icon: const Icon(Icons.refresh_rounded, size: 22),
              tooltip: '새 대화',
              onPressed: () {
                showDialog(
                  context: context,
                  builder: (_) => AlertDialog(
                    title: const Text('새 대화 시작'),
                    content: const Text('현재 대화 내역이 삭제됩니다.\n새 대화를 시작할까요?'),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('취소'),
                      ),
                      TextButton(
                        onPressed: () {
                          chat.clearChat();
                          setState(() => _selectedSources = null);
                          Navigator.pop(context);
                        },
                        child: const Text(
                          '시작',
                          style: TextStyle(color: AppColors.primary),
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
        IconButton(
          icon: const Icon(Icons.logout_rounded, size: 22),
          tooltip: '로그아웃',
          onPressed: () => _showLogoutDialog(context),
        ),
      ],
    );
  }

  bool _isSameDay(DateTime a, DateTime b) {
    return a.year == b.year && a.month == b.month && a.day == b.day;
  }
}

// ─── 날짜 구분선 ──────────────────────────────────────
// ─── 드로어 폭 조절 핸들 ──────────────────────────────────

/// 드로어 오른쪽 가장자리에 드래그 핸들을 얹어 폭을 조절할 수 있게 한다.
class _ResizableDrawerContent extends StatefulWidget {
  final Widget child;
  final void Function(double deltaX) onResize;
  final VoidCallback onResizeEnd;

  const _ResizableDrawerContent({
    required this.child,
    required this.onResize,
    required this.onResizeEnd,
  });

  @override
  State<_ResizableDrawerContent> createState() =>
      _ResizableDrawerContentState();
}

class _ResizableDrawerContentState extends State<_ResizableDrawerContent> {
  bool _hovered = false;
  bool _dragging = false;

  @override
  Widget build(BuildContext context) {
    final active = _hovered || _dragging;

    return Stack(
      children: [
        Positioned.fill(child: widget.child),
        Positioned(
          top: 0,
          bottom: 0,
          right: 0,
          width: 12,
          child: MouseRegion(
            cursor: SystemMouseCursors.resizeLeftRight,
            onEnter: (_) => setState(() => _hovered = true),
            onExit: (_) => setState(() => _hovered = false),
            child: GestureDetector(
              behavior: HitTestBehavior.translucent,
              onHorizontalDragStart: (_) => setState(() => _dragging = true),
              onHorizontalDragUpdate: (d) => widget.onResize(d.delta.dx),
              onHorizontalDragEnd: (_) {
                setState(() => _dragging = false);
                widget.onResizeEnd();
              },
              onHorizontalDragCancel: () => setState(() => _dragging = false),
              child: Align(
                alignment: Alignment.centerRight,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 120),
                  width: active ? 3 : 1,
                  height: double.infinity,
                  color: active ? AppColors.primaryDark : AppColors.divider,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _DateDivider extends StatelessWidget {
  final DateTime date;
  const _DateDivider({required this.date});

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    String label;
    if (_isSameDay(date, now)) {
      label = '오늘';
    } else if (_isSameDay(date, now.subtract(const Duration(days: 1)))) {
      label = '어제';
    } else {
      label = '${date.month}월 ${date.day}일';
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 40),
      child: Row(
        children: [
          const Expanded(child: Divider(color: AppColors.divider)),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(
              label,
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ),
          const Expanded(child: Divider(color: AppColors.divider)),
        ],
      ),
    );
  }

  bool _isSameDay(DateTime a, DateTime b) {
    return a.year == b.year && a.month == b.month && a.day == b.day;
  }
}
