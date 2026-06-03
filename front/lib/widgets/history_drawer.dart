import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/chat_models.dart';
import '../services/chat_provider.dart';
import '../theme.dart';

class HistoryDrawer extends StatelessWidget {
  /// 세션 로드 완료 후 호출 (ChatScreen에서 selectedSources 초기화 등)
  final VoidCallback? onSessionLoaded;

  const HistoryDrawer({super.key, this.onSessionLoaded});

  @override
  Widget build(BuildContext context) {
    return Consumer<ChatProvider>(
      builder: (context, chat, _) {
        return Column(
          children: [
            _DrawerHeader(chat: chat),
            const Divider(height: 1, color: AppColors.divider),
            if (chat.isLoadingSessions)
              const Expanded(
                child: Center(child: CircularProgressIndicator()),
              )
            else if (chat.sessions.isEmpty)
              const _EmptyState()
            else
              Expanded(
                child: _SessionList(
                  sessions:        chat.sessions,
                  activeSessionId: chat.activeSessionId,
                  isLoading:       chat.isLoadingSession,
                  onTap: (id) {
                    Navigator.of(context).pop();
                    chat.loadSession(id);
                    onSessionLoaded?.call();
                  },
                  onDelete: (session) => _confirmDelete(context, chat, session),
                ),
              ),
          ],
        );
      },
    );
  }

  void _confirmDelete(
      BuildContext context, ChatProvider chat, ChatSession session) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('대화 삭제'),
        content: Text('"${session.title}"을(를) 삭제할까요?'),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              chat.deleteSession(session.id);
            },
            child: const Text(
              '삭제',
              style: TextStyle(color: AppColors.error),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── 헤더 ─────────────────────────────────────────────────

class _DrawerHeader extends StatelessWidget {
  final ChatProvider chat;
  const _DrawerHeader({required this.chat});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 8, 12),
        child: Row(
          children: [
            const Icon(
              Icons.history_rounded,
              size: 20,
              color: AppColors.primaryDark,
            ),
            const SizedBox(width: 8),
            const Text(
              '대화 기록',
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w600,
                color: AppColors.textPrimary,
              ),
            ),
            const Spacer(),
            if (chat.isLoadingSessions)
              const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              IconButton(
                icon: const Icon(Icons.refresh_rounded, size: 20),
                color: AppColors.textSecondary,
                tooltip: '새로고침',
                onPressed: () => chat.fetchSessions(),
              ),
            IconButton(
              icon: const Icon(Icons.close_rounded, size: 20),
              color: AppColors.textSecondary,
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── 빈 상태 ──────────────────────────────────────────────

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return const Expanded(
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.chat_bubble_outline_rounded,
              size: 48,
              color: AppColors.textTertiary,
            ),
            SizedBox(height: 12),
            Text(
              '저장된 대화가 없습니다',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── 세션 목록 ────────────────────────────────────────────

class _SessionList extends StatelessWidget {
  final List<ChatSession> sessions;
  final int? activeSessionId;
  final bool isLoading;
  final void Function(int id) onTap;
  final void Function(ChatSession session) onDelete;

  const _SessionList({
    required this.sessions,
    required this.activeSessionId,
    required this.isLoading,
    required this.onTap,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final items = _buildGroupedItems(sessions);

    return Stack(
      children: [
        ListView.builder(
          padding: const EdgeInsets.only(bottom: 24, top: 4),
          itemCount: items.length,
          itemBuilder: (context, index) {
            final item = items[index];
            if (item is String) {
              return _SectionHeader(label: item);
            }
            final session  = item as ChatSession;
            final isActive = session.id == activeSessionId;
            return _SessionTile(
              session:  session,
              isActive: isActive,
              onTap:    () => onTap(session.id),
              onDelete: () => onDelete(session),
            );
          },
        ),
        // 세션 로드 중 오버레이
        if (isLoading)
          const Positioned.fill(
            child: ColoredBox(
              color: Color(0x55FFFFFF),
              child: Center(child: CircularProgressIndicator()),
            ),
          ),
      ],
    );
  }

  List<Object> _buildGroupedItems(List<ChatSession> sessions) {
    final now       = DateTime.now();
    final today     = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final weekAgo   = today.subtract(const Duration(days: 7));

    String? currentGroup;
    final result = <Object>[];

    for (final session in sessions) {
      final date = DateTime(
        session.createdAt.year,
        session.createdAt.month,
        session.createdAt.day,
      );

      final String group;
      if (!date.isBefore(today)) {
        group = '오늘';
      } else if (!date.isBefore(yesterday)) {
        group = '어제';
      } else if (!date.isBefore(weekAgo)) {
        group = '이번 주';
      } else {
        group = '이전';
      }

      if (group != currentGroup) {
        result.add(group);
        currentGroup = group;
      }
      result.add(session);
    }

    return result;
  }
}

// ─── 섹션 헤더 ────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String label;
  const _SectionHeader({required this.label});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: AppColors.textTertiary,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

// ─── 세션 아이템 ──────────────────────────────────────────

class _SessionTile extends StatelessWidget {
  final ChatSession session;
  final bool isActive;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  const _SessionTile({
    required this.session,
    required this.isActive,
    required this.onTap,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: ListTile(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        selected: isActive,
        selectedTileColor: AppColors.primarySurface,
        contentPadding: const EdgeInsets.only(left: 12, right: 4),
        leading: Icon(
          Icons.chat_rounded,
          size: 17,
          color: isActive ? AppColors.primaryDark : AppColors.textTertiary,
        ),
        title: Text(
          session.title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 14,
            fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
            color: isActive ? AppColors.primaryDark : AppColors.textPrimary,
          ),
        ),
        subtitle: Text(
          _formatDate(session.createdAt),
          style: const TextStyle(fontSize: 11, color: AppColors.textTertiary),
        ),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline_rounded, size: 17),
          color: AppColors.textTertiary,
          tooltip: '삭제',
          onPressed: onDelete,
        ),
        onTap: onTap,
      ),
    );
  }

  String _formatDate(DateTime dt) {
    final now       = DateTime.now();
    final today     = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final date      = DateTime(dt.year, dt.month, dt.day);

    if (!date.isBefore(today)) {
      final h = dt.hour.toString().padLeft(2, '0');
      final m = dt.minute.toString().padLeft(2, '0');
      return '$h:$m';
    } else if (!date.isBefore(yesterday)) {
      return '어제';
    } else {
      return '${dt.month}월 ${dt.day}일';
    }
  }
}
