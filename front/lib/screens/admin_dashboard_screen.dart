import 'package:flutter/material.dart';
import '../models/admin_models.dart';
import '../services/admin_service.dart';
import '../theme.dart';

class AdminDashboardScreen extends StatefulWidget {
  final AdminApiService adminService;

  const AdminDashboardScreen({super.key, required this.adminService});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  late Future<VideoStatusResponse> _future;
  bool _isRefreshing = false;

  @override
  void initState() {
    super.initState();
    _future = widget.adminService.getVideoStatus();
  }

  void _loadCached() {
    setState(() {
      _future = widget.adminService.getVideoStatus();
    });
  }

  void _forceRefresh() {
    setState(() {
      _isRefreshing = true;
      _future = widget.adminService.refreshVideoStatus().whenComplete(() {
        if (mounted) setState(() => _isRefreshing = false);
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('영상 상태 관리'),
        actions: [
          IconButton(
            icon: _isRefreshing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.sync_rounded),
            tooltip: 'YouTube 재확인',
            onPressed: _isRefreshing ? null : _forceRefresh,
          ),
        ],
      ),
      body: FutureBuilder<VideoStatusResponse>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 16),
                  Text('YouTube 영상 상태 확인 중...'),
                ],
              ),
            );
          }

          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.error_outline,
                        size: 48, color: AppColors.error),
                    const SizedBox(height: 16),
                    Text(
                      '${snapshot.error}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton.icon(
                      onPressed: _loadCached,
                      icon: const Icon(Icons.refresh),
                      label: const Text('다시 시도'),
                    ),
                  ],
                ),
              ),
            );
          }

          return _buildContent(snapshot.data!);
        },
      ),
    );
  }

  Widget _buildContent(VideoStatusResponse data) {
    return RefreshIndicator(
      onRefresh: () async => _loadCached(),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildStatsCards(data),
          const SizedBox(height: 24),
          if (data.problemVideos.isNotEmpty) ...[
            _buildSectionHeader('문제 영상', data.problemCount, AppColors.error),
            const SizedBox(height: 8),
            ...data.problemVideos.map(_buildVideoCard),
            const SizedBox(height: 24),
          ],
          _buildSectionHeader('전체 영상', data.total, AppColors.primary),
          const SizedBox(height: 8),
          ...data.videos.map(_buildVideoCard),
          const SizedBox(height: 16),
          if (data.checkedAt != null)
            Center(
              child: Text(
                '마지막 확인: ${_formatDate(data.checkedAt!)}',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _buildStatsCards(VideoStatusResponse data) {
    return Row(
      children: [
        Expanded(
            child: _StatCard(
                label: '전체', count: data.total, color: AppColors.primary)),
        const SizedBox(width: 12),
        Expanded(
            child: _StatCard(
                label: '정상', count: data.okCount, color: const Color(0xFF4CAF50))),
        const SizedBox(width: 12),
        Expanded(
            child: _StatCard(
                label: '문제', count: data.problemCount, color: AppColors.error)),
      ],
    );
  }

  Widget _buildSectionHeader(String title, int count, Color color) {
    return Row(
      children: [
        Container(
          width: 4,
          height: 20,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '$title ($count)',
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.bold),
        ),
      ],
    );
  }

  Widget _buildVideoCard(VideoStatusItem video) {
    final color = _statusColor(video.status);
    final label = _statusLabel(video.status);

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        leading: Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        title: Text(
          video.title.isNotEmpty ? video.title : '(제목 없음)',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 14),
        ),
        subtitle: Text(
          video.message,
          style: TextStyle(color: color, fontSize: 12),
        ),
        trailing: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: color.withValues(alpha: 0.4)),
          ),
          child: Text(
            label,
            style: TextStyle(
                fontSize: 12, color: color, fontWeight: FontWeight.w600),
          ),
        ),
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'ok':
        return const Color(0xFF4CAF50);
      case 'private':
        return const Color(0xFFFF9800);
      case 'unlisted':
        return const Color(0xFFFFC107);
      case 'unavailable':
        return AppColors.error;
      default:
        return AppColors.textTertiary;
    }
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'ok':
        return '정상';
      case 'private':
        return '비공개';
      case 'unlisted':
        return '일부공개';
      case 'unavailable':
        return '없음';
      default:
        return '오류';
    }
  }

  String _formatDate(String iso) {
    try {
      final dt = DateTime.parse(iso).toLocal();
      return '${dt.month}/${dt.day} '
          '${dt.hour.toString().padLeft(2, '0')}:'
          '${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return iso;
    }
  }
}

class _StatCard extends StatelessWidget {
  final String label;
  final int count;
  final Color color;

  const _StatCard(
      {required this.label, required this.count, required this.color});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
        child: Column(
          children: [
            Text(
              count.toString(),
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    color: color,
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 4),
            Text(label,
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(color: AppColors.textSecondary)),
          ],
        ),
      ),
    );
  }
}
