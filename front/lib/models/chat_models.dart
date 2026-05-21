/// 채팅 메시지 모델
class ChatMessage {
  final String id;
  final String content;
  final bool isUser;
  final DateTime timestamp;
  final SourceInfo? sources;
  final bool isLoading;

  ChatMessage({
    required this.id,
    required this.content,
    required this.isUser,
    required this.timestamp,
    this.sources,
    this.isLoading = false,
  });

  ChatMessage copyWith({
    String? content,
    SourceInfo? sources,
    bool? isLoading,
  }) {
    return ChatMessage(
      id: id,
      content: content ?? this.content,
      isUser: isUser,
      timestamp: timestamp,
      sources: sources ?? this.sources,
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

/// 출처 정보 통합
class SourceInfo {
  final List<WebSource> webSources;
  final List<BookSource> bookSources;
  final List<VideoSource> videoSources;

  SourceInfo({
    this.webSources = const [],
    this.bookSources = const [],
    this.videoSources = const [],
  });

  bool get isEmpty =>
      webSources.isEmpty && bookSources.isEmpty && videoSources.isEmpty;

  int get totalCount =>
      webSources.length + bookSources.length + videoSources.length;
}

/// 웹 출처
class WebSource {
  final String title;
  final String url;
  final String snippet;
  final double score;

  WebSource({
    required this.title,
    required this.url,
    this.snippet = '',
    this.score = 0.0,
  });

  factory WebSource.fromMap(Map<String, dynamic> map) {
    return WebSource(
      title: map['title'] ?? '',
      url: map['url'] ?? '',
      snippet: (map['content'] ?? '').toString().length > 150
          ? '${(map['content'] ?? '').toString().substring(0, 150)}...'
          : map['content'] ?? '',
      score: (map['score'] ?? 0).toDouble(),
    );
  }
}

/// 책 출처
class BookSource {
  final String bookName;
  final int page;
  final String snippet;
  final double score;
  final List<String> images;

  BookSource({
    required this.bookName,
    required this.page,
    this.snippet = '',
    this.score = 0.0,
    this.images = const [],
  });

  factory BookSource.fromMap(Map<String, dynamic> map) {
    return BookSource(
      bookName: map['book'] ?? '',
      page: map['page'] ?? 0,
      snippet: (map['content'] ?? '').toString().length > 150
          ? '${(map['content'] ?? '').toString().substring(0, 150)}...'
          : map['content'] ?? '',
      score: (map['score'] ?? 0).toDouble(),
      images: List<String>.from(map['images'] ?? []),
    );
  }
}

/// 영상 출처
class VideoSource {
  final String videoId;
  final String title;
  final double startTime;
  final double endTime;
  final String url;
  final String snippet;
  final double score;

  VideoSource({
    required this.videoId,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.url,
    this.snippet = '',
    this.score = 0.0,
  });

  factory VideoSource.fromMap(Map<String, dynamic> map) {
    return VideoSource(
      videoId: map['video_id'] ?? '',
      title: map['title'] ?? '',
      startTime: (map['start'] ?? 0).toDouble(),
      endTime: (map['end'] ?? 0).toDouble(),
      url: map['url'] ?? '',
      snippet: (map['content'] ?? '').toString().length > 150
          ? '${(map['content'] ?? '').toString().substring(0, 150)}...'
          : map['content'] ?? '',
      score: (map['score'] ?? 0).toDouble(),
    );
  }

  /// YouTube embed URL 추출
  String get youtubeEmbedUrl {
    final ytId = youtubeId;
    if (ytId == null || ytId.isEmpty) return '';
    return 'https://www.youtube.com/embed/$ytId?start=${startTime.toInt()}';
  }

  /// YouTube video ID 추출
  /// youtu.be/ID?t=... → pathSegments[0]
  /// youtube.com/watch?v=ID → queryParameters['v']
  String? get youtubeId {
    try {
      final uri = Uri.parse(url);
      if (uri.host.contains('youtu.be')) {
        final id = uri.pathSegments.isNotEmpty ? uri.pathSegments.first : '';
        return id.isNotEmpty ? id : null;
      }
      if (uri.host.contains('youtube.com')) {
        var v = uri.queryParameters['v'];
        // ?v=ID?t=79s 형태의 비정상 URL에서 ?t=... 제거
        if (v != null && v.contains('?')) v = v.split('?').first;
        return (v != null && v.isNotEmpty) ? v : null;
      }
    } catch (_) {}
    return null;
  }
}

/// 추천 질문
class SuggestedQuestion {
  final String text;

  SuggestedQuestion({required this.text});
}
