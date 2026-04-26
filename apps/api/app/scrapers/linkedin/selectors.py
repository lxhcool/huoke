from __future__ import annotations


class LinkedinSelectors:
    login_username_input_candidates = [
        "input#username",
        "input[name='session_key']",
        "input[name='username']",
    ]

    login_password_input_candidates = [
        "input#password",
        "input[name='session_password']",
        "input[name='password']",
        "input[type='password']",
    ]

    login_submit_candidates = [
        "button[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('登录')",
    ]

    login_success_candidates = [
        "input[placeholder*='Search']",
        "input[aria-label*='Search']",
        "a[href='/feed/']",
        "a[href*='/mynetwork/']",
    ]

    company_result_row_candidates = [
        "ul.reusable-search__entity-result-list > li",
        "main ul > li",
        ".search-results-container li",
    ]

    contact_result_row_candidates = [
        "ul.reusable-search__entity-result-list > li",
        "main ul > li",
        ".search-results-container li",
    ]

    # 公司搜索结果中的链接
    company_link_candidates = [
        "a[href*='/company/']",
        ".entity-result__title-text a",
        "a.app-aware-link[href*='/company/']",
    ]

    # 联系人搜索结果中的链接
    contact_link_candidates = [
        "a[href*='/in/']",
        ".entity-result__title-text a",
        "a.app-aware-link[href*='/in/']",
    ]

    # 翻页
    pagination_next_candidates = [
        "button[aria-label='Next']",
        "button[aria-label='下一页']",
        ".artdeco-pagination__button--next",
        "li.artdeco-pagination__indicator--next button",
        "button:has-text('Next')",
    ]

    # 公司主页详情
    company_name_candidates = [
        "h1",
        "h1.org-top-card-summary__title",
        "[data-test-id='company-name']",
        ".org-top-card-summary__title",
    ]

    company_industry_candidates = [
        "dt:has-text('Industry') + dd",
        "dt:has-text('行业') + dd",
        ".org-page-details__definition-term:has-text('Industry') + .org-page-details__definition-text",
        "[data-test-id='industry']",
        "dd.org-about-company-module__company-industry",
    ]

    company_size_candidates = [
        "dt:has-text('Company size') + dd",
        "dt:has-text('公司规模') + dd",
        "dt:has-text('Employees') + dd",
        ".org-page-details__definition-term:has-text('Company size') + .org-page-details__definition-text",
        "[data-test-id='company-size']",
        "dd.org-about-company-module__company-size",
    ]

    company_website_candidates = [
        "dt:has-text('Website') + dd a",
        "dt:has-text('网站') + dd a",
        "a[data-test-id='company-website-url']",
        ".org-about-company-module__website a",
        "dt:has-text('Website') + dd span a",
    ]

    company_description_candidates = [
        ".org-about-company-module__description",
        "[data-test-id='about-us']",
        ".org-top-card-summary__tagline",
        "p.org-about-us-organization-description__text",
    ]

    company_headquarters_candidates = [
        "dt:has-text('Headquarters') + dd",
        "dt:has-text('总部') + dd",
        "dt:has-text('Address') + dd",
        "[data-test-id='headquarters']",
        "dd.org-about-company-module__headquarters",
    ]

    # 联系人信息（搜索结果页）
    contact_name_candidates = [
        ".entity-result__title-text",
        ".entity-result__title-text a span",
        "span.entity-result__title-line",
    ]

    contact_title_candidates = [
        ".entity-result__primary-subtitle",
        ".entity-result__summary",
        ".entity-result__secondary-subtitle",
    ]

    contact_company_candidates = [
        ".entity-result__secondary-subtitle",
        ".entity-result__summary p",
    ]

