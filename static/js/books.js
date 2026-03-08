let bookSlideIndex = 1;
let bookCurrentScroll = 0;
const bookPath = window.location.href;
let lastTappedBook = null;

function openBookSlider() {
    bookCurrentScroll = document.documentElement.scrollTop || document.body.scrollTop;
    document.body.classList.add("noscroll");
    document.getElementById('book-slider').style.display = "grid";
    document.addEventListener('keydown', keyboardBookSlider);
}

function closeBookSlider() {
    document.getElementById('book-slider').style.display = "none";
    document.removeEventListener('keydown', keyboardBookSlider);
    if (history.replaceState) {
        history.replaceState({}, bookPath, bookPath);
    }
    document.body.classList.remove("noscroll");
    window.scrollTo(0, bookCurrentScroll);
}

function plusBookSlides(n) {
    showBookSlides(bookSlideIndex += n);
}

function currentBookSlide(n) {
    showBookSlides(bookSlideIndex = n);
}

function showBookSlides(n) {
    var slides = document.querySelectorAll("#book-slider .slide");
    if (n > slides.length) {
        bookSlideIndex = 1;
    }
    if (n < 1) {
        bookSlideIndex = slides.length;
    }
    for (var i = 0; i < slides.length; i++) {
        slides[i].style.display = "none";
    }
    if (history.replaceState) {
        history.replaceState({}, bookPath, slides[bookSlideIndex - 1].getAttribute("path"));
    }
    slides[bookSlideIndex - 1].scrollTo(0, 0);
    slides[bookSlideIndex - 1].style.display = "flex";
}

function keyboardBookSlider(event) {
    if (event.key === "ArrowLeft") {
        plusBookSlides(-1);
    } else if (event.key === "ArrowRight") {
        plusBookSlides(1);
    } else if (event.key === "Escape") {
        closeBookSlider();
    }
}

// Touch device support: first tap shows preview, second tap opens slider
function handleBookTap(slideNum, el) {
    var isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    if (!isTouchDevice) {
        openBookSlider();
        currentBookSlide(slideNum);
        return;
    }
    var box = el.closest('.book-box');
    if (lastTappedBook === box) {
        // Second tap — open the slider
        lastTappedBook = null;
        box.classList.remove('tapped');
        openBookSlider();
        currentBookSlide(slideNum);
    } else {
        // First tap — show preview
        if (lastTappedBook) {
            lastTappedBook.classList.remove('tapped');
        }
        lastTappedBook = box;
        box.classList.add('tapped');
    }
}
