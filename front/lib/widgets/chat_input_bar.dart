// 하단 입력 바
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme.dart';

class ChatInputBar extends StatefulWidget {
  final ValueChanged<String> onSend;
  final bool isLoading;

  const ChatInputBar({
    super.key,
    required this.onSend,
    this.isLoading = false,
  });

  @override
  State<ChatInputBar> createState() => _ChatInputBarState();
}

class _ChatInputBarState extends State<ChatInputBar> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  bool _hasText = false;
  bool _isFocused = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final hasText = _controller.text.trim().isNotEmpty;
      if (hasText != _hasText) setState(() => _hasText = hasText);
    });
    _focusNode.addListener(() {
      if (_focusNode.hasFocus != _isFocused) {
        setState(() => _isFocused = _focusNode.hasFocus);
      }
    });
    _focusNode.onKeyEvent = (node, event) {
      if (event is KeyDownEvent &&
          event.logicalKey == LogicalKeyboardKey.enter &&
          !HardwareKeyboard.instance.isShiftPressed) {
        // 한글 등 IME 조합 중의 Enter는 '글자 확정'이므로 전송하면 안 된다.
        // 이 핸들러는 IME보다 먼저 실행되어, 여기서 전송·clear를 하면
        // 확정되지 않은 마지막 글자가 비워진 입력창에 남는다.
        if (_controller.value.composing.isValid) {
          return KeyEventResult.ignored;
        }
        // 답변 생성 중에는 전송하지 않되, 줄바꿈이 끼어들지 않도록 이벤트는 삼킨다.
        if (!widget.isLoading) _handleSend();
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    };
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _handleSend() {
    // IME 조합이 끝나지 않은 상태에서 보내면 마지막 글자가 입력창에 남는다.
    if (_controller.value.composing.isValid) return;
    final text = _controller.text.trim();
    if (text.isEmpty || widget.isLoading) return;
    widget.onSend(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    // 홈 인디케이터/제스처 바 영역을 피하되, 그 위로도 최소 여백을 확보해
    // 입력 바가 화면 맨 아래에 붙어 보이지 않도록 한다.
    final bottomInset = MediaQuery.of(context).viewPadding.bottom;
    final canSend = _hasText && !widget.isLoading;

    return Container(
      padding: EdgeInsets.fromLTRB(16, 12, 16, bottomInset + 16),
      decoration: const BoxDecoration(
        color: AppColors.background,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOut,
            constraints: const BoxConstraints(maxHeight: 160),
            decoration: BoxDecoration(
              // 배경(#F8F7F4)과 확실히 구분되도록 흰 서피스를 쓴다.
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(28),
              border: Border.all(
                color: _isFocused
                    ? AppColors.primary
                    : AppColors.divider,
                width: _isFocused ? 2 : 1.5,
              ),
              boxShadow: [
                BoxShadow(
                  color: _isFocused
                      ? AppColors.primary.withOpacity(0.16)
                      : Colors.black.withOpacity(0.06),
                  blurRadius: _isFocused ? 16 : 10,
                  offset: const Offset(0, 3),
                ),
              ],
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                // 텍스트 입력
                Expanded(
                  child: TextField(
                    controller: _controller,
                    focusNode: _focusNode,
                    maxLines: null,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _handleSend(),
                    inputFormatters: [
                      // IME 조합 확정용 Enter가 개행으로 남지 않도록 걸러낸다.
                      FilteringTextInputFormatter.deny(RegExp(r'[\r\n]')),
                    ],
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          height: 1.4,
                          leadingDistribution:
                              TextLeadingDistribution.even,
                        ),
                    cursorColor: AppColors.primaryDark,
                    decoration: InputDecoration(
                      hintText: 'BeBot에게 무엇이든 물어보세요',
                      filled: false,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      disabledBorder: InputBorder.none,
                      isDense: true,
                      contentPadding: const EdgeInsets.fromLTRB(22, 12, 8, 18),
                      hintStyle:
                          Theme.of(context).textTheme.bodyLarge?.copyWith(
                                color: AppColors.textSecondary,
                                height: 1.4,
                                leadingDistribution:
                                    TextLeadingDistribution.even,
                              ),
                    ),
                  ),
                ),

                // 전송 버튼
                Padding(
                  padding: const EdgeInsets.fromLTRB(0, 4, 6, 4),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 180),
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      color: canSend
                          ? AppColors.primary
                          : AppColors.surfaceVariant,
                      borderRadius: BorderRadius.circular(22),
                    ),
                    child: Material(
                      color: Colors.transparent,
                      child: InkWell(
                        onTap: canSend ? _handleSend : null,
                        borderRadius: BorderRadius.circular(22),
                        child: widget.isLoading
                            ? const Padding(
                                padding: EdgeInsets.all(13),
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(
                                    AppColors.textTertiary,
                                  ),
                                ),
                              )
                            : Icon(
                                Icons.arrow_upward_rounded,
                                color: canSend
                                    ? Colors.white
                                    : AppColors.textTertiary,
                                size: 22,
                              ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
