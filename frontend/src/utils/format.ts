import dayjs from 'dayjs';

export const formatDateTime = (value: string) =>
  dayjs(value).format('MMM D, YYYY h:mm A');

export const formatDate = (value: string) =>
  dayjs(value).format('MMM D, YYYY');

export const toDateTimeInput = (value: string) =>
  dayjs(value).format('YYYY-MM-DDTHH:mm');
