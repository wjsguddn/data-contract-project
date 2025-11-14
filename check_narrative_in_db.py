"""
DB에 narrative_report가 저장되었는지 확인
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.shared.database import ValidationResult

# DB 연결
engine = create_engine("sqlite:///data/database/contracts.db")
Session = sessionmaker(bind=engine)
db = Session()

try:
    # 최신 ValidationResult 조회
    result = db.query(ValidationResult).order_by(
        ValidationResult.created_at.desc()
    ).first()
    
    if not result or not result.final_report:
        print("❌ ValidationResult 또는 final_report가 없습니다.")
        exit(1)
    
    print(f"✅ Contract ID: {result.contract_id}")
    print(f"✅ Created At: {result.created_at}\n")
    
    # user_articles 확인
    final_report = result.final_report
    user_articles = final_report.get("user_articles", [])
    
    print(f"📋 총 {len(user_articles)}개 조항\n")
    
    # narrative_report 확인
    narrative_count = 0
    for article in user_articles:
        if article.get('narrative_report'):
            narrative_count += 1
    
    print(f"✅ narrative_report가 있는 조항: {narrative_count}개")
    print(f"❌ narrative_report가 없는 조항: {len(user_articles) - narrative_count}개\n")
    
    if narrative_count > 0:
        print("="*80)
        print("\n📄 첫 번째 narrative_report 샘플:\n")
        for article in user_articles:
            if article.get('narrative_report'):
                print(f"조항: {article.get('user_article_title')}")
                print("-"*80)
                print(article['narrative_report'][:500])
                print("\n... (생략)")
                break
    else:
        print("⚠️ 모든 조항에 narrative_report가 없습니다!")
        print("\n첫 번째 조항 구조:")
        if user_articles:
            first = user_articles[0]
            print(f"  - 키: {list(first.keys())}")
            print(f"  - user_article_title: {first.get('user_article_title')}")
            print(f"  - matched_standard_articles: {len(first.get('matched_standard_articles', []))}개")
            print(f"  - insufficient_items: {len(first.get('insufficient_items', []))}개")
            print(f"  - checklist_results: {len(first.get('checklist_results', []))}개")

finally:
    db.close()
