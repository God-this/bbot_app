class VideoStatusItem {
  final String videoId;
  final String title;
  final String url;
  final String? youtubeId;
  final String status;
  final String message;

  const VideoStatusItem({
    required this.videoId,
    required this.title,
    required this.url,
    this.youtubeId,
    required this.status,
    required this.message,
  });

  factory VideoStatusItem.fromMap(Map<String, dynamic> map) {
    return VideoStatusItem(
      videoId: map['video_id']?.toString() ?? '',
      title: map['title'] ?? '',
      url: map['url'] ?? '',
      youtubeId: map['youtube_id']?.toString(),
      status: map['status'] ?? 'error',
      message: map['message'] ?? '',
    );
  }

  bool get isOk => status == 'ok';
}

class VideoStatusResponse {
  final int total;
  final int okCount;
  final int problemCount;
  final List<VideoStatusItem> videos;
  final String? checkedAt;

  const VideoStatusResponse({
    required this.total,
    required this.okCount,
    required this.problemCount,
    required this.videos,
    this.checkedAt,
  });

  factory VideoStatusResponse.fromMap(Map<String, dynamic> map) {
    return VideoStatusResponse(
      total: map['total'] ?? 0,
      okCount: map['ok_count'] ?? 0,
      problemCount: map['problem_count'] ?? 0,
      videos: (map['videos'] as List<dynamic>? ?? [])
          .map((v) => VideoStatusItem.fromMap(v as Map<String, dynamic>))
          .toList(),
      checkedAt: map['checked_at'],
    );
  }

  List<VideoStatusItem> get problemVideos =>
      videos.where((v) => !v.isOk).toList();
}
